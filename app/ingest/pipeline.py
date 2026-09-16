"""Zrodlo -> strony -> akapity -> indeks.

Caly przebieg jest deterministyczny: zero wywolan modelu. Model wchodzi dopiero
przy odpowiadaniu na pytanie i przy szukaniu sprzecznosci.
"""

import re

import fitz

from app.db.base import SessionLocal
from sqlalchemy.orm.attributes import flag_modified

from app.answer.cytaty import bez_odstepow
from app.db.models import Chunk, Label, Message, Page, Source, SourceLabel
from concurrent.futures import ThreadPoolExecutor

from app.ingest.chunks import split_into_paragraphs
from app.ingest.ocr import MIN_PEWNOSC, RAZEM_STRON, gdzie_jest_tekst, ma_tresc, odczytaj_obraz
from app.ingest.storage import download_bytes, upload_bytes
from app.search.index import index_source


def label_code(text: str) -> str:
    """Kod etykiety z tekstu. "Bioróżnorodność" i "bioróżnorodność" daja ten sam
    kod - redaktor pokazal dokladnie ten problem: "dodalem z duzej litery,
    dodalem z malej, stworzylo mi dwa"."""
    mapping = str.maketrans("ąćęłńóśźż", "acelnoszz")
    slug = text.strip().lower().translate(mapping)
    return re.sub(r"[^a-z0-9]+", "_", slug).strip("_")[:64]


def _attach_labels(db, source: Source, labels: list[str]) -> None:
    for raw in labels:
        name = raw.strip()
        if not name:
            continue
        code = label_code(name)
        if not code:
            continue
        label = db.query(Label).filter_by(code=code).one_or_none()
        if label is None:
            label = Label(code=code, name=name)
            db.add(label)
            db.flush()
        if db.query(SourceLabel).filter_by(source_id=source.id, label_id=label.id).one_or_none() is None:
            db.add(SourceLabel(source_id=source.id, label_id=label.id))


def add_source(
    *,
    title: str,
    data: bytes,
    kind: str,
    labels: list[str] | None = None,
    author: str | None = None,
    description: str | None = None,
) -> int:
    """Zapisuje zrodlo i plik. Nie przetwarza - to robi process_source w tle."""
    db = SessionLocal()
    try:
        source = Source(
            title=title.strip()[:512],
            author=(author or None),
            description=(description or None),
            kind=kind,
            object_key="",
            status="pending",
        )
        db.add(source)
        db.flush()

        extension = "pdf" if kind == "pdf" else "txt"
        source.object_key = f"sources/{source.id}/original.{extension}"
        upload_bytes(source.object_key, data)

        _attach_labels(db, source, labels or [])
        db.commit()
        return source.id
    finally:
        db.close()


def process_source(source_id: int) -> None:
    """Dzieli zrodlo na strony i akapity, po czym indeksuje.

    Bledy zapisujemy przy zrodle zamiast tylko rzucac: redaktor ma zobaczyc w
    panelu, ze cos poszlo nie tak, a nie czekac w nieskonczonosc na "przetwarzanie"."""
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        if source is None:
            raise ValueError(f"źródło {source_id} nie istnieje")

        data = download_bytes(source.object_key)
        pages_text = _extract_pages(source.kind, data)

        # Przetwarzanie tego samego zrodla drugi raz musi zaczac od czystego
        # stanu. Bez tego akapity z poprzedniego podzialu zostawaly w bazie
        # obok nowych i wychodzily w wynikach jako drugi egzemplarz ksiazki.
        stare_strony = [p.id for p in db.query(Page).filter_by(source_id=source.id).all()]
        if stare_strony:
            db.query(Chunk).filter(Chunk.page_id.in_(stare_strony)).delete(synchronize_session=False)
            db.query(Page).filter(Page.id.in_(stare_strony)).delete(synchronize_session=False)
            db.flush()

        for number, (text, z_obrazu) in enumerate(pages_text, start=1):
            page = Page(source_id=source.id, number=number, z_obrazu=z_obrazu)
            db.add(page)
            db.flush()
            for seq, paragraph in enumerate(split_into_paragraphs(text)):
                db.add(Chunk(source_id=source.id, page_id=page.id, seq=seq, text=paragraph))

        db.commit()
        index_source(source_id)
        przepnij_odnosniki(db, source_id)

        source = db.get(Source, source_id)
        source.status = "ready"
        source.error_text = None
        db.commit()
    except Exception as exc:
        db.rollback()
        source = db.get(Source, source_id)
        if source is not None:
            source.status = "error"
            source.error_text = str(exc)[:2000]
            db.commit()
        raise
    finally:
        db.close()


def przepnij_odnosniki(db, source_id: int) -> int:
    """Odnosniki w zapisanych odpowiedziach po ponownym podziale ksiazki.

    Akapity dostaja przy ponownym przetworzeniu nowe numery, wiec kazda
    zapisana odpowiedz wskazywala w pustke - klikniecie przypisu nie pokazywalo
    niczego. Odnajdujemy nowy akapit po zapisanej tresci starego: wpis zrodla
    trzyma cala jego tresc, a porownanie po samych literach przechodzi mimo
    poprawionego odczytu PDF-a.

    Zwraca liczbe przepietych odnosnikow."""
    istnieja = {c.id for c in db.query(Chunk).filter_by(source_id=source_id).all()}
    strony = {p.number: p.id for p in db.query(Page).filter_by(source_id=source_id).all()}
    akapity_strony: dict[int, list[Chunk]] = {}
    for chunk in db.query(Chunk).filter_by(source_id=source_id).all():
        akapity_strony.setdefault(chunk.page_id, []).append(chunk)

    przepiete = 0
    for message in db.query(Message).filter_by(role="assistant").all():
        dane = message.answer_json or {}
        mapa: dict[int, int] = {}
        for wpis in dane.get("sources", []):
            if wpis.get("source_id") != source_id or wpis.get("chunk_id") in istnieja:
                continue
            odcisk = bez_odstepow(wpis.get("text", ""))[:120]
            if len(odcisk) < 40:
                continue
            kandydaci = akapity_strony.get(strony.get(wpis.get("page")), [])
            trafiony = next((c for c in kandydaci if odcisk in bez_odstepow(c.text)), None)
            if trafiony is not None:
                mapa[wpis["chunk_id"]] = trafiony.id
        if not mapa:
            continue

        for wpis in dane.get("sources", []):
            nowy = mapa.get(wpis["chunk_id"])
            if nowy:
                wpis["chunk_id"] = nowy
                wpis["text"] = db.get(Chunk, nowy).text
        for czesc in dane.get("sentences", []):
            for wpis in czesc.get("sources") or []:
                wpis["chunk_id"] = mapa.get(wpis["chunk_id"], wpis["chunk_id"])
            if czesc.get("source"):
                czesc["source"]["chunk_id"] = mapa.get(
                    czesc["source"]["chunk_id"], czesc["source"]["chunk_id"]
                )
        # Bez tego SQLAlchemy nie zauwaza zmiany w polu JSON i zapis przepada.
        flag_modified(message, "answer_json")
        przepiete += len(mapa)

    db.commit()
    return przepiete


def _extract_pages(kind: str, data: bytes) -> list[tuple[str, bool]]:
    """Tekst kazdej strony wraz z informacja, czy trzeba go bylo odczytac z obrazu.

    Nie pytamy "czy to jest skan", tylko "gdzie na tej stronie jest tresc".
    Dzieki temu ta sama reguła obsluguje ksiazke tekstowa, skan i ksiazke
    mieszana - a klient niczego nie musi nam mowic przy wgrywaniu."""
    if kind != "pdf":
        return [(data.decode("utf-8"), False)]

    # TEXT_INHIBIT_SPACES jest tu konieczne, nie kosmetyczne. Bez tej flagi
    # PyMuPDF wstawia spacje wszedzie tam, gdzie w PDF-ie jest wiekszy
    # odstep miedzy literami - w ksiazce Sulka dawalo to "Poleca m podlewa
    # c pomido ry system em lin ii kroplujacyc h" w co trzecim akapicie.
    # Psulo to wszystko naraz: wyszukiwanie po slowach nie trafialo w
    # "kroplujacych", wektor liczyl sie z siekanego tekstu, a cytat modelu
    # (przeczytany poprawnie, bo litery sa na miejscu) nie zgadzal sie
    # z akapitem i odpowiedz dostawala "Nie znalazlem w zrodle".
    flagi = fitz.TEXTFLAGS_TEXT | fitz.TEXT_INHIBIT_SPACES | fitz.TEXT_DEHYPHENATE

    strony: list[tuple[str, bool]] = []
    do_odczytu: list[int] = []

    with fitz.open(stream=data, filetype="pdf") as document:
        for numer, strona in enumerate(document):
            warstwa = strona.get_text("text", flags=flagi)
            pokrycie_tekstu, pokrycie_obrazow = gdzie_jest_tekst(strona)
            strony.append((warstwa, False))

            # Tekst pokrywa strone - nie ma czego szukac w obrazach.
            if pokrycie_tekstu >= 0.05:
                continue
            # Tekstu nie ma albo jest go sladowo. Jesli jest obraz, tresc
            # siedzi wlasnie w nim.
            if pokrycie_obrazow >= 0.2:
                do_odczytu.append(numer)

        if do_odczytu:
            # Rownolegle, bo Tesseract idzie osobnym procesem i czekamy tylko
            # na wejscie-wyjscie. Osiemnascie sekund na strone razy trzysta
            # stron to poltorej godziny; w czterech watkach niecala godzina.
            with ThreadPoolExecutor(max_workers=RAZEM_STRON) as pula:
                odczyty = list(pula.map(lambda n: odczytaj_obraz(document[n]), do_odczytu))

            for numer, (odczyt, pewnosc) in zip(do_odczytu, odczyty):
                if pewnosc < MIN_PEWNOSC or not ma_tresc(odczyt):
                    continue  # fotografia - odczyt to szum, zostaje co bylo
                # Naglowek rozdzialu z warstwy tekstowej zostaje - jest
                # dokladny co do znaku, a OCR moze go przekrecic.
                warstwa = strony[numer][0]
                strony[numer] = (f"{warstwa}\n{odczyt}".strip(), True)

    return strony

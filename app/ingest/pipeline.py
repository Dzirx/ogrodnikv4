"""Zrodlo -> strony -> akapity -> indeks.

Caly przebieg jest deterministyczny: zero wywolan modelu. Model wchodzi dopiero
przy odpowiadaniu na pytanie i przy szukaniu sprzecznosci.
"""

import re

import fitz

from app.db.base import SessionLocal
from app.db.models import Chunk, Label, Page, Source, SourceLabel
from app.ingest.chunks import split_into_paragraphs
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

        for number, text in enumerate(pages_text, start=1):
            page = Page(source_id=source.id, number=number)
            db.add(page)
            db.flush()
            for seq, paragraph in enumerate(split_into_paragraphs(text)):
                db.add(Chunk(source_id=source.id, page_id=page.id, seq=seq, text=paragraph))

        db.commit()
        index_source(source_id)

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


def _extract_pages(kind: str, data: bytes) -> list[str]:
    """Tekst per strona. Wklejony tekst to jedna strona.

    Wylacznie warstwa tekstowa, bez OCR - skany nie wejda i trzeba to
    powiedziec klientowi wprost, zamiast udawac, ze dziala."""
    if kind == "pdf":
        # TEXT_INHIBIT_SPACES jest tu konieczne, nie kosmetyczne. Bez tej flagi
        # PyMuPDF wstawia spacje wszedzie tam, gdzie w PDF-ie jest wiekszy
        # odstep miedzy literami - w ksiazce Sulka dawalo to "Poleca m podlewa
        # c pomido ry system em lin ii kroplujacyc h" w co trzecim akapicie.
        # Psulo to wszystko naraz: wyszukiwanie po slowach nie trafialo w
        # "kroplujacych", wektor liczyl sie z siekanego tekstu, a cytat modelu
        # (przeczytany poprawnie, bo litery sa na miejscu) nie zgadzal sie
        # z akapitem i odpowiedz dostawala "Nie znalazlem w zrodle".
        flagi = fitz.TEXTFLAGS_TEXT | fitz.TEXT_INHIBIT_SPACES | fitz.TEXT_DEHYPHENATE
        with fitz.open(stream=data, filetype="pdf") as document:
            return [page.get_text("text", flags=flagi) for page in document]
    return [data.decode("utf-8")]

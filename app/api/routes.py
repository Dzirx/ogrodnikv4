"""Trasy panelu. Trzy ekrany: Pytania, Źródła, Do rozstrzygnięcia.

Redaktor ma robić trzy rzeczy: dodać źródło, zapytać, rozstrzygnąć rozbieżność.
Nic poza tym nie ma prawa pojawić się w nawigacji.
"""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.answer.build import BEZ_SPACJI
from app.db.base import get_db
from app.db.models import (
    Chunk,
    Conflict,
    Conversation,
    ConversationSource,
    Label,
    Message,
    Page,
    Source,
    SourceLabel,
)
from app.ingest.pipeline import add_source
from app.ingest.podglad import render_strony
from app.ingest.storage import download_bytes
from app.tasks import queue, przetworz_zrodlo, odpowiedz_na_pytanie

router = APIRouter()
templates = Jinja2Templates(directory="app/api/templates")


def _wspolne(db: Session) -> dict:
    """Dane widoczne w każdym ekranie - licznik przy zakładce z konfliktami."""
    return {"liczba_konfliktow": db.query(Conflict).filter_by(status="open").count()}


def _pogrupuj_zrodla(zrodla: list[Source]) -> list[tuple[str | None, list[Source]]]:
    """Źródła w grupach po etykietach, żeby dało się zaznaczyć temat naraz.

    Źródło z kilkoma etykietami trafia do każdej z nich - tak jak książka o
    pomidorze i bioróżnorodności jest przydatna przy obu tematach. Źródła bez
    etykiety idą na koniec, bez nagłówka."""
    grupy: dict[str, list[Source]] = {}
    bez_etykiety: list[Source] = []
    for zrodlo in zrodla:
        if zrodlo.labels:
            for etykieta in zrodlo.labels:
                grupy.setdefault(etykieta.name, []).append(zrodlo)
        else:
            bez_etykiety.append(zrodlo)

    wynik: list[tuple[str | None, list[Source]]] = sorted(grupy.items())
    if bez_etykiety:
        wynik.append((None, bez_etykiety))
    return wynik


# Ile wątków pokazujemy w pasku po lewej, zanim pojawi się "Pokaż więcej".
POKAZ_ROZMOW = 20

# To samo dla listy źródeł.
POKAZ_ZRODEL = 30


def _historia(db: Session, ile: int, biezaca: Conversation | None = None) -> dict:
    """Wątki w pasku po lewej - przycięte, nie wszystkie.

    Przy setce pytań pasek rósł bez końca i trzeba było przewijać go do dołu,
    żeby cokolwiek znaleźć. Najnowsze wątki są tym, czego się szuka."""
    ile = max(POKAZ_ROZMOW, min(ile, 500))
    rozmowy = db.query(Conversation).order_by(Conversation.id.desc()).limit(ile).all()
    # Otwarty wątek musi być widoczny, choćby był starszy niż próg - inaczej
    # wchodzisz w rozmowę i znika ona z listy, w której właśnie ją kliknąłeś.
    if biezaca is not None and all(r.id != biezaca.id for r in rozmowy):
        rozmowy.append(biezaca)
    return {
        "rozmowy": rozmowy,
        "starsze": max(db.query(Conversation).count() - ile, 0),
        "nastepne": ile + POKAZ_ROZMOW,
    }


@router.get("/", response_class=HTMLResponse)
def pytania(request: Request, historia: int = POKAZ_ROZMOW, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "strona": "pytania",
            **_historia(db, historia),
            "zrodla": (gotowe := db.query(Source).filter_by(status="ready").order_by(Source.title).all()),
            "pogrupowane": _pogrupuj_zrodla(gotowe),
            "rozmowa": None,
            "wiadomosci": [],
            "podglad": None,
            **_wspolne(db),
        },
    )


@router.get("/rozmowy/{rozmowa_id}", response_class=HTMLResponse)
def rozmowa(
    request: Request,
    rozmowa_id: int,
    podglad: int | None = None,
    w: int | None = None,
    z: int | None = None,
    historia: int = POKAZ_ROZMOW,
    db: Session = Depends(get_db),
):
    conversation = db.get(Conversation, rozmowa_id)
    if conversation is None:
        raise HTTPException(404, "Nie ma takiej rozmowy")

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "strona": "pytania",
            **_historia(db, historia, conversation),
            "zrodla": (gotowe := db.query(Source).filter_by(status="ready").order_by(Source.title).all()),
            "pogrupowane": _pogrupuj_zrodla(gotowe),
            "rozmowa": conversation,
            "wiadomosci": db.query(Message).filter_by(conversation_id=rozmowa_id).order_by(Message.id).all(),
            "podglad": _podglad(db, podglad, w, z),
            **_wspolne(db),
        },
    )


def _zrodla_czesci(czesc: dict) -> list[dict]:
    """Przypisy jednego kawałka tekstu.

    Starsze rozmowy mają w bazie pojedyncze "source" przy całym zdaniu — wtedy
    jednostką tekstu było zdanie, nie fragment zdania. Czytamy jedno i drugie,
    żeby zapisane odpowiedzi nadal się wyświetlały."""
    if czesc.get("sources") is not None:
        return czesc["sources"]
    zrodlo = czesc.get("source")
    return [zrodlo] if zrodlo else []


def czesci_odpowiedzi(odpowiedz: dict) -> list[dict]:
    """Kawałki odpowiedzi gotowe do sklejenia w akapit.

    Model oddaje tekst pocięty tam, gdzie kończy się zasięg przypisu — kawałek
    to zwykle część zdania, nie całe zdanie. Brakującą spację dokładamy tutaj,
    bo model czasem o niej zapomina, a sklejone słowa wyglądają na błąd
    programu."""
    wynik: list[dict] = []
    for czesc in odpowiedz.get("sentences", []):
        # Bez ucinania spacji na koncu przypis odklei sie od slowa, przy ktorym
        # stoi, i przyklei do nastepnego zdania: "owoców. ¹Podczas upalow".
        tekst = czesc.get("text", "").rstrip()
        poprzedni = wynik[-1]["text"] if wynik else ""
        if poprzedni and tekst and not tekst[0].isspace() and tekst[0] not in BEZ_SPACJI and not poprzedni.endswith(" "):
            tekst = " " + tekst
        wynik.append(
            {
                "text": tekst,
                "verified": czesc.get("verified", False),
                "zrodla": _zrodla_czesci(czesc),
                "ustalenie": czesc.get("ustalenie"),
            }
        )
    return _bez_powtorzonych_znacznikow(wynik)


def _bez_powtorzonych_znacznikow(czesci: list[dict]) -> list[dict]:
    """Odnośnik pokazujemy raz na odcinek, nie przy każdym kawałku.

    Model podaje źródło do KAŻDEGO kawałka i tak ma zostać - na tym stoi
    weryfikacja. Ale rysowanie wszystkich cyferek robiło z odpowiedzi pracę
    naukową: osiem odnośników na sześć zdań, po jednym przy każdym zdaniu.

    Cyferka staje więc tam, gdzie kończy się odcinek oparty na tym samym
    akapicie - czasem w środku zdania, czasem po dwóch zdaniach. Miejsca nie
    wymuszamy, bo koniec zdania byłby tylko inną sztywną regułą.

    Kawałki bez źródła (spoiwo) nie przerywają odcinka - "a", " — " czy
    przecinek nie zmieniają tego, skąd pochodzi zdanie."""
    for numer, czesc in enumerate(czesci):
        czesc["znaczniki"] = czesc["zrodla"]
        if not czesc["zrodla"]:
            continue
        nastepny = next(
            (k for k in czesci[numer + 1 :] if k["zrodla"] or k.get("ustalenie")), None
        )
        if nastepny is not None and _te_same(nastepny["zrodla"], czesc["zrodla"]):
            czesc["znaczniki"] = []
    return czesci


def _te_same(a: list[dict], b: list[dict]) -> bool:
    return {z["marker"] for z in a} == {z["marker"] for z in b}


def tekst_ze_znacznikami(odpowiedz: dict) -> str:
    """Tekst odpowiedzi z przypisami w postaci [1], [2] - do pola edycji.

    Redaktor poprawia tekst RAZEM ze znacznikami i sam decyduje, gdzie mają
    zostać. Bez tego po edycji nie dałoby się ich umieścić w treści, bo tekst
    jest już jego i nie wiadomo, które zdanie z którego akapitu pochodzi -
    a przypisy na marginesie to nie to samo, co przypis przy zdaniu."""
    kawalki = []
    for czesc in czesci_odpowiedzi(odpowiedz):
        kawalki.append(czesc["text"])
        # Te same odnośniki, które widać w odpowiedzi - inaczej po otwarciu
        # okna edycji tekst wyglądałby inaczej niż przed chwilą na ekranie.
        kawalki.extend(f"[{zrodlo['marker']}]" for zrodlo in czesc["znaczniki"])
    return "".join(kawalki)


_ZNACZNIK_RE = re.compile(r"\[(\d{1,2})\]")


def rozbij_znaczniki(tekst: str, zrodla: list[dict]) -> list[dict]:
    """Dzieli poprawiony tekst na fragmenty i znaczniki [N].

    Szablon nie może wstawić odnośnika w środek napisu, a wstawianie surowego
    HTML-a z bazy jest wykluczone - więc rozbijamy tekst tutaj i szablon składa
    go z bezpiecznych kawałków."""
    po_numerze = {z["marker"]: z for z in zrodla}
    czesci: list[dict] = []
    ostatni = 0
    for dopasowanie in _ZNACZNIK_RE.finditer(tekst):
        if dopasowanie.start() > ostatni:
            czesci.append({"tekst": tekst[ostatni : dopasowanie.start()]})
        numer = int(dopasowanie.group(1))
        zrodlo = po_numerze.get(numer)
        if zrodlo:
            czesci.append({"znacznik": numer, "zrodlo": zrodlo})
        else:
            # Numer, którego nie ma wśród źródeł (redaktor wpisał go sam) -
            # zostawiamy jako zwykły tekst, zamiast udawać odnośnik.
            czesci.append({"tekst": dopasowanie.group(0)})
        ostatni = dopasowanie.end()
    if ostatni < len(tekst):
        czesci.append({"tekst": tekst[ostatni:]})
    return czesci


def _rozbij_na_cytat(akapit: str, cytat: str) -> list[dict]:
    """Dzieli akapit na części przed cytatem, cytat i po nim.

    Podświetlamy cytat w TEKŚCIE, nie na obrazie strony. Rysowanie na stronie
    PDF okazało się zawodne: współrzędne z odczytu tekstu i z renderu rozjeżdżają
    się w tej książce o całą linijkę (mediabox zaczyna się od y=7,83, cropbox od
    zera), więc żółta ramka lądowała przy sąsiednim zdaniu i myliła bardziej,
    niż pomagała. W tekście nie ma żadnych układów współrzędnych do pomylenia.

    Porównujemy po uproszczeniu białych znaków i myślników, bo model przepisuje
    cytat z PDF-a, który łamie wiersze gdzie popadnie."""
    if not cytat or cytat == akapit:
        return [{"tekst": akapit, "cytat": bool(cytat)}]

    uproszczony_akapit = _uprosc(akapit)
    pozycja = uproszczony_akapit.find(_uprosc(cytat))
    if pozycja < 0:
        return [{"tekst": akapit, "cytat": False}]

    # Pozycję z tekstu uproszczonego przekładamy na oryginał, licząc znaki
    # nie-białe - inaczej podświetlenie przesunęłoby się o każdą zwiniętą spację.
    granice = _granice_w_oryginale(akapit, pozycja, len(_uprosc(cytat)))
    if granice is None:
        return [{"tekst": akapit, "cytat": False}]

    poczatek, koniec = granice
    czesci = []
    if akapit[:poczatek].strip():
        czesci.append({"tekst": akapit[:poczatek], "cytat": False})
    czesci.append({"tekst": akapit[poczatek:koniec], "cytat": True})
    if akapit[koniec:].strip():
        czesci.append({"tekst": akapit[koniec:], "cytat": False})
    return czesci


def _uprosc(tekst: str) -> str:
    """Do szukania cytatu w akapicie - bez żadnych białych znaków.

    Ta sama zasada co przy weryfikacji: odstęp nie jest treścią. Dopóki
    porównywaliśmy ze spacjami, cytat zapisany przed poprawką odczytu PDF-a
    ("p rzekomposto wany kom post") przechodził weryfikację, ale nie dawał się
    podświetlić - odnośnik otwierał stronę i nic na niej nie zaznaczał."""
    tekst = tekst.replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    return re.sub(r"\s+", "", tekst).lower()


def _granice_w_oryginale(akapit: str, pozycja: int, dlugosc: int) -> tuple[int, int] | None:
    """Przelicza pozycję z tekstu bez odstępów na indeksy w oryginale."""
    licznik = 0
    poczatek = koniec = None
    for indeks, znak in enumerate(akapit):
        if znak.isspace():
            continue
        if licznik == pozycja and poczatek is None:
            poczatek = indeks
        if licznik == pozycja + dlugosc:
            koniec = indeks
            break
        licznik += 1
    if poczatek is None:
        return None
    return poczatek, (koniec if koniec is not None else len(akapit))


def _podglad(
    db: Session, chunk_id: int | None, message_id: int | None = None, zdanie: int | None = None
) -> dict | None:
    """Akapit pokazywany w prawej kolumnie wraz ze stroną źródła.

    Zaznaczamy CYTAT, nie cały akapit. Akapit potrafi mieć sześćset znaków i
    obejmować kilka różnych rzeczy naraz - na stronie o suchej zgniliźnie
    jeden akapit zawiera i przyczyny choroby, i zalecenie dotyczące odczynu
    gleby. Zaznaczony w całości świecił na żółto przyczyny choroby, choć
    odpowiedź dotyczyła pH."""
    if chunk_id is None:
        return None
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        return None

    do_zaznaczenia = chunk.text
    if message_id is not None and zdanie is not None:
        wiadomosc = db.get(Message, message_id)
        zdania = (wiadomosc.answer_json or {}).get("sentences", []) if wiadomosc else []
        if 0 <= zdanie < len(zdania):
            # Kawalek moze miec kilka przypisow - bierzemy cytat z tego, ktory
            # prowadzi do ogladanego akapitu.
            for zrodlo in _zrodla_czesci(zdania[zdanie]):
                if zrodlo.get("chunk_id") == chunk_id and zrodlo.get("quote"):
                    do_zaznaczenia = zrodlo["quote"]
                    break
    page = db.get(Page, chunk.page_id)
    source = db.get(Source, chunk.source_id)
    return {
        "chunk_id": chunk.id,
        "text": chunk.text,
        "fragmenty": _rozbij_na_cytat(chunk.text, do_zaznaczenia),
        "zaznacz": do_zaznaczenia,
        "page": page.number,
        "source_id": source.id,
        "source_title": source.title,
        "source_kind": source.kind,
    }


@router.post("/pytania")
def nowe_pytanie(
    pytanie: str = Form(...),
    zrodla: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
):
    """Nowa rozmowa. Tytuł z pierwszego pytania - samo nazywa wątek."""
    tekst = pytanie.strip()
    if not tekst:
        return RedirectResponse("/", status_code=303)

    conversation = Conversation(title=tekst[:120])
    db.add(conversation)
    db.flush()
    for source_id in zrodla:
        db.add(ConversationSource(conversation_id=conversation.id, source_id=source_id))
    db.commit()

    _zapytaj(db, conversation.id, tekst)
    return RedirectResponse(f"/rozmowy/{conversation.id}", status_code=303)


@router.post("/rozmowy/{rozmowa_id}/pytania")
def kolejne_pytanie(rozmowa_id: int, pytanie: str = Form(...), db: Session = Depends(get_db)):
    tekst = pytanie.strip()
    if tekst:
        _zapytaj(db, rozmowa_id, tekst)
    return RedirectResponse(f"/rozmowy/{rozmowa_id}", status_code=303)


def _zapytaj(db: Session, rozmowa_id: int, tekst: str) -> None:
    """Pytanie zapisujemy od razu, odpowiedź liczy się w tle.

    Wyszukiwanie, model i sprawdzenie cytatów nie mieszczą się w żądaniu HTTP."""
    db.add(Message(conversation_id=rozmowa_id, role="user", text=tekst, status="ready"))
    odpowiedz = Message(conversation_id=rozmowa_id, role="assistant", text="", status="pending")
    db.add(odpowiedz)
    db.commit()
    queue.enqueue(odpowiedz_na_pytanie, odpowiedz.id, job_timeout=600)


@router.post("/rozmowy/{rozmowa_id}/zrodla")
def zmien_zakres(rozmowa_id: int, zrodla: list[int] = Form(default=[]), db: Session = Depends(get_db)):
    """Zmiana zakresu źródeł rozmowy.

    Dotyczy kolejnych pytań. Wcześniejszych odpowiedzi nie ruszamy: opierały
    się na tym, co było zaznaczone wtedy, i przepisywanie tego wstecz
    znaczyłoby, że cytaty przestają odpowiadać temu, co redaktor widział."""
    if db.get(Conversation, rozmowa_id) is None:
        raise HTTPException(404, "Nie ma takiej rozmowy")

    db.query(ConversationSource).filter_by(conversation_id=rozmowa_id).delete()
    for source_id in zrodla:
        db.add(ConversationSource(conversation_id=rozmowa_id, source_id=source_id))
    db.commit()
    return RedirectResponse(f"/rozmowy/{rozmowa_id}", status_code=303)


@router.post("/rozmowy/{rozmowa_id}/wiadomosci/{wiadomosc_id}")
def popraw_odpowiedz(
    rozmowa_id: int,
    wiadomosc_id: int,
    tekst: str = Form(...),
    db: Session = Depends(get_db),
):
    """Ręczna poprawka odpowiedzi.

    Redaktor poprawia gotowy tekst, nie zdania z przypisami - to ma być
    edycja, a nie żonglowanie numerami. Źródła zostają: treść nadal się na
    nich opiera, tylko powiedziana po jego myśli. Puste pole cofa poprawkę."""
    wiadomosc = db.get(Message, wiadomosc_id)
    if wiadomosc is None or wiadomosc.conversation_id != rozmowa_id:
        raise HTTPException(404, "Nie ma takiej wiadomości")

    oczyszczony = tekst.strip()
    wiadomosc.edited_text = oczyszczony or None
    wiadomosc.edited_at = datetime.utcnow() if oczyszczony else None
    db.commit()
    return RedirectResponse(f"/rozmowy/{rozmowa_id}", status_code=303)


@router.get("/zrodla", response_class=HTMLResponse)
def zrodla(
    request: Request,
    blad: str | None = None,
    szukaj: str = "",
    etykieta: str | None = None,
    ile: int = POKAZ_ZRODEL,
    db: Session = Depends(get_db),
):
    """Lista źródeł - szukanie po tytule, zawężenie etykietą, reszta za linkiem.

    Klient zapowiada sześćdziesiąt warzyw, czyli kilkaset książek. Jedna lista
    ciągiem przestaje być listą - trzeba wiedzieć, czego się szuka, zanim się
    zacznie przewijać."""
    ile = max(POKAZ_ZRODEL, min(ile, 500))
    fraza = szukaj.strip()

    zapytanie = db.query(Source)
    if fraza:
        wzorzec = f"%{fraza}%"
        zapytanie = zapytanie.filter(or_(Source.title.ilike(wzorzec), Source.author.ilike(wzorzec)))
    if etykieta:
        zapytanie = zapytanie.join(SourceLabel, SourceLabel.source_id == Source.id).join(
            Label, Label.id == SourceLabel.label_id
        ).filter(Label.code == etykieta)

    pasujace = zapytanie.count()
    wybrane = zapytanie.order_by(Source.id.desc()).limit(ile).all()

    # Jedno zapytanie zamiast COUNT na każde źródło - przy stu książkach to
    # była setka zapytań na każde wejście na ekran.
    liczniki = dict(
        db.query(Chunk.source_id, func.count(Chunk.id)).group_by(Chunk.source_id).all()
    )

    etykiety = (
        db.query(Label.code, Label.name, func.count(SourceLabel.source_id))
        .join(SourceLabel, SourceLabel.label_id == Label.id)
        .group_by(Label.code, Label.name)
        .order_by(Label.name)
        .all()
    )

    return templates.TemplateResponse(
        "zrodla.html",
        {
            "request": request,
            "strona": "zrodla",
            "zrodla": wybrane,
            "liczba_akapitow": liczniki,
            "wszystkich": db.query(Source).count(),
            "pasujacych": pasujace,
            "starsze": max(pasujace - ile, 0),
            "nastepne": ile + POKAZ_ZRODEL,
            "szukaj": fraza,
            "etykieta": etykieta,
            "etykiety": etykiety,
            "blad": blad,
            **_wspolne(db),
        },
    )


@router.post("/zrodla")
async def dodaj_zrodlo(
    tytul: str = Form(...),
    etykiety: str = Form(""),
    autor: str = Form(""),
    plik: UploadFile | None = None,
    tekst: str = Form(""),
):
    """Źródło od razu idzie do przetworzenia - bez osobnego przycisku.

    W pierwszej wersji wgranie książki i wyciągnięcie z niej treści były dwoma
    krokami, mimo że przy tym drugim nie ma żadnej decyzji do podjęcia."""
    ma_plik = plik is not None and bool(plik.filename)
    if not ma_plik and not tekst.strip():
        return RedirectResponse("/zrodla?blad=Wybierz+plik+albo+wklej+tekst", status_code=303)

    dane = await plik.read() if ma_plik else tekst.encode("utf-8")
    source_id = add_source(
        title=tytul,
        data=dane,
        kind="pdf" if ma_plik else "text",
        labels=[e for e in etykiety.split(",") if e.strip()],
        author=autor or None,
    )
    queue.enqueue(przetworz_zrodlo, source_id, job_timeout=3600)
    return RedirectResponse("/zrodla", status_code=303)


@router.get("/zrodla/{source_id}", response_class=HTMLResponse)
def zrodlo(
    request: Request,
    source_id: int,
    strona: int = 1,
    rozmowa: int | None = None,
    akapit: int | None = None,
    db: Session = Depends(get_db),
):
    """Podgląd książki w panelu.

    Przedtem tytuł na liście prowadził do surowego pliku PDF w nowej karcie -
    redaktor wychodził z panelu i wracał przyciskiem przeglądarki."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Nie ma takiego źródła")

    numery = [p.number for p in db.query(Page).filter_by(source_id=source_id).order_by(Page.number).all()]
    biezaca = strona if strona in numery else (numery[0] if numery else 1)
    page = db.query(Page).filter_by(source_id=source_id, number=biezaca).one_or_none()
    akapity = (
        db.query(Chunk).filter_by(page_id=page.id).order_by(Chunk.seq).all() if page else []
    )

    return templates.TemplateResponse(
        "zrodlo.html",
        {
            "request": request,
            "strona": "zrodla",
            "zrodlo": source,
            "strony": numery,
            "biezaca": biezaca,
            "akapity": akapity,
            # Powrót tam, skąd redaktor przyszedł - razem z otwartym podglądem
            # akapitu. Bez tego wejście w książkę z rozmowy było ślepą uliczką:
            # zostawał przycisk wstecz przeglądarki albo szukanie wątku od nowa.
            "powrot": (
                f"/rozmowy/{rozmowa}?podglad={akapit}" if rozmowa and akapit
                else f"/rozmowy/{rozmowa}" if rozmowa
                else None
            ),
            **_wspolne(db),
        },
    )


@router.get("/zrodla/{source_id}/strona/{numer}.png")
def obraz_strony(
    source_id: int,
    numer: int,
    chunk: int | None = None,
    cytat: str | None = None,
    db: Session = Depends(get_db),
):
    """Strona źródła jako obraz, z podświetlonym cytowanym fragmentem.

    Sam numer strony nie wystarcza: książkowa strona ma kilka tysięcy znaków
    i szukanie na niej jednego zdania to dokładnie ta praca, której redaktor
    miał nie wykonywać."""
    source = db.get(Source, source_id)
    if source is None or source.kind != "pdf":
        raise HTTPException(404, "Nie ma takiego pliku PDF")

    # Cytat ma pierwszeństwo przed całym akapitem - jest krótszy i wskazuje
    # dokładnie to zdanie, na którym oparta jest odpowiedź.
    fragment = cytat or (db.get(Chunk, chunk).text if chunk else None)
    try:
        obraz = render_strony(download_bytes(source.object_key), numer, fragment)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    # Bez tego przegladarka trzyma obraz w pamieci podrecznej pod tym samym
    # adresem i po poprawce zaznaczenia pokazuje stara wersje - mylace przy
    # sprawdzaniu, czy cytat trafia we wlasciwe miejsce.
    return Response(
        content=obraz, media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.get("/zrodla/{source_id}/plik")
def plik_zrodla(source_id: int, db: Session = Depends(get_db)):
    """Oryginalny plik - podgląd w prawej kolumnie otwiera go z #page=N."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Nie ma takiego źródła")
    rozszerzenie = "pdf" if source.kind == "pdf" else "txt"
    typ = "application/pdf" if source.kind == "pdf" else "text/plain; charset=utf-8"
    # Nazwa pliku w naglowku - inaczej przegladarka zapisuje go jako "plik".
    # Przegladanie odbywa sie na ekranie zrodla (strony jako obrazy), wiec tu
    # chodzi wylacznie o pobranie oryginalu.
    nazwa = re.sub(r"[^\w\- ]", "", source.title).strip()[:80] or f"zrodlo-{source.id}"
    return Response(
        content=download_bytes(source.object_key),
        media_type=typ,
        headers={"Content-Disposition": f'attachment; filename="{nazwa}.{rozszerzenie}"'},
    )


@router.get("/konflikty", response_class=HTMLResponse)
def konflikty(request: Request, db: Session = Depends(get_db)):
    otwarte = db.query(Conflict).filter_by(status="open").order_by(Conflict.id).all()
    opcje = [o for k in otwarte for o in k.options]
    chunks = {c.id: c for c in db.query(Chunk).filter(Chunk.id.in_([o.chunk_id for o in opcje])).all()} if opcje else {}
    pages = {p.id: p for p in db.query(Page).filter(Page.id.in_([c.page_id for c in chunks.values()])).all()} if chunks else {}
    sources = {s.id: s for s in db.query(Source).filter(Source.id.in_([c.source_id for c in chunks.values()])).all()} if chunks else {}

    zrodla_opcji = {}
    for opcja in opcje:
        chunk = chunks.get(opcja.chunk_id)
        if chunk is not None:
            zrodla_opcji[opcja.id] = f"{sources[chunk.source_id].title}, strona {pages[chunk.page_id].number}"

    return templates.TemplateResponse(
        "konflikty.html",
        {
            "request": request,
            "strona": "konflikty",
            "konflikty": otwarte,
            "zrodla_opcji": zrodla_opcji,
            "rozstrzygniete": db.query(Conflict).filter_by(status="resolved").order_by(Conflict.id.desc()).all(),
            **_wspolne(db),
        },
    )


@router.post("/konflikty/{konflikt_id}")
def rozstrzygnij(
    konflikt_id: int,
    wartosc: str = Form(...),
    wlasna: str = Form(""),
    db: Session = Depends(get_db),
):
    """Redaktor wybiera jedną z wartości albo wpisuje własną.

    Własna wartość to trzecia możliwość, o którą poprosił wprost: "ani jedno,
    ani drugie, 5,7, bo będzie bezpieczniej". Nie wymyśla jej model, tylko
    człowiek - dlatego w odpowiedziach będzie oznaczona jako ustalenie
    redakcji, nie cytat ze źródła."""
    konflikt = db.get(Conflict, konflikt_id)
    if konflikt is None:
        raise HTTPException(404, "Nie ma takiego konfliktu")

    wlasne = wartosc == "__wlasna__"
    przyjeta = wlasna.strip() if wlasne else wartosc.strip()
    if not przyjeta:
        return RedirectResponse("/konflikty", status_code=303)

    konflikt.resolved_value = przyjeta[:255]
    konflikt.resolved_origin = "editorial" if wlasne else "source"
    konflikt.status = "resolved"
    konflikt.resolved_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/konflikty", status_code=303)


# Funkcje pomocnicze dla szablonow - przypisane na koncu, bo definiowane wyzej.
templates.env.globals["czesci_odpowiedzi"] = czesci_odpowiedzi
templates.env.globals["tekst_ze_znacznikami"] = tekst_ze_znacznikami
templates.env.globals["rozbij_znaczniki"] = rozbij_znaczniki

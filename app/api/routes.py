"""Trasy panelu. Trzy ekrany: Pytania, Źródła, Do rozstrzygnięcia.

Redaktor ma robić trzy rzeczy: dodać źródło, zapytać, rozstrzygnąć rozbieżność.
Nic poza tym nie ma prawa pojawić się w nawigacji.
"""

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import Chunk, Conflict, Conversation, ConversationSource, Message, Page, Source
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


@router.get("/", response_class=HTMLResponse)
def pytania(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "strona": "pytania",
            "rozmowy": db.query(Conversation).order_by(Conversation.id.desc()).all(),
            "zrodla": (gotowe := db.query(Source).filter_by(status="ready").order_by(Source.title).all()),
            "pogrupowane": _pogrupuj_zrodla(gotowe),
            "rozmowa": None,
            "wiadomosci": [],
            "podglad": None,
            **_wspolne(db),
        },
    )


@router.get("/rozmowy/{rozmowa_id}", response_class=HTMLResponse)
def rozmowa(request: Request, rozmowa_id: int, podglad: int | None = None, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, rozmowa_id)
    if conversation is None:
        raise HTTPException(404, "Nie ma takiej rozmowy")

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "strona": "pytania",
            "rozmowy": db.query(Conversation).order_by(Conversation.id.desc()).all(),
            "zrodla": (gotowe := db.query(Source).filter_by(status="ready").order_by(Source.title).all()),
            "pogrupowane": _pogrupuj_zrodla(gotowe),
            "rozmowa": conversation,
            "wiadomosci": db.query(Message).filter_by(conversation_id=rozmowa_id).order_by(Message.id).all(),
            "podglad": _podglad(db, podglad),
            **_wspolne(db),
        },
    )


def _podglad(db: Session, chunk_id: int | None) -> dict | None:
    """Akapit pokazywany w prawej kolumnie wraz ze stroną PDF.

    Redaktor przy każdym cytacie tracił kontekst i musiał szukać, skąd on jest.
    Teraz klika znacznik i widzi tę stronę obok tekstu."""
    if chunk_id is None:
        return None
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        return None
    page = db.get(Page, chunk.page_id)
    source = db.get(Source, chunk.source_id)
    return {
        "chunk_id": chunk.id,
        "text": chunk.text,
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


@router.get("/zrodla", response_class=HTMLResponse)
def zrodla(request: Request, blad: str | None = None, db: Session = Depends(get_db)):
    wszystkie = db.query(Source).order_by(Source.id.desc()).all()
    liczba_akapitow = {
        source.id: db.query(Chunk).filter_by(source_id=source.id).count() for source in wszystkie
    }
    return templates.TemplateResponse(
        "zrodla.html",
        {
            "request": request,
            "strona": "zrodla",
            "zrodla": wszystkie,
            "liczba_akapitow": liczba_akapitow,
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
def obraz_strony(source_id: int, numer: int, chunk: int | None = None, db: Session = Depends(get_db)):
    """Strona źródła jako obraz, z podświetlonym cytowanym fragmentem.

    Sam numer strony nie wystarcza: książkowa strona ma kilka tysięcy znaków
    i szukanie na niej jednego zdania to dokładnie ta praca, której redaktor
    miał nie wykonywać."""
    source = db.get(Source, source_id)
    if source is None or source.kind != "pdf":
        raise HTTPException(404, "Nie ma takiego pliku PDF")

    fragment = db.get(Chunk, chunk).text if chunk else None
    try:
        obraz = render_strony(download_bytes(source.object_key), numer, fragment)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return Response(content=obraz, media_type="image/png")


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
    from datetime import datetime

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

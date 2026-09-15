"""Indeks semantyczny akapitow w Qdrant.

Punkt ma id akapitu, wiec trafienie prowadzi wprost do tekstu, strony i
zrodla - bez tego nie da sie pokazac cytatu ani otworzyc PDF-a na wlasciwej
stronie.
"""

import re

from openai import OpenAI
from sqlalchemy import case, literal
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FilterSelector,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Chunk, Page, Source

# text-embedding-3-large
EMBEDDING_DIM = 3072
BATCH_SIZE = 100

_qdrant = QdrantClient(url=settings.qdrant_url)
_openai = OpenAI(api_key=settings.openai_api_key)


def ensure_collection() -> None:
    existing = {c.name for c in _qdrant.get_collections().collections}
    if settings.qdrant_collection not in existing:
        _qdrant.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
    # Indeks zakladany osobno i idempotentnie - dla kolekcji, ktora juz
    # istniala, galaz wyzej sie nie wykona.
    _qdrant.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="source_id",
        field_schema=PayloadSchemaType.INTEGER,
    )


def embed(texts: list[str]) -> list[list[float]]:
    response = _openai.embeddings.create(model=settings.embedding_model, input=texts)
    return [item.embedding for item in response.data]


def index_source(source_id: int) -> int:
    """Liczy wektory akapitow zrodla i wysyla do Qdranta. Zwraca liczbe akapitow."""
    ensure_collection()
    # Punkty po poprzednim przetworzeniu tego zrodla musza zniknac. Sam upsert
    # ich nie ruszy, bo nowe akapity dostaja nowe numery - stare zostawaly
    # w indeksie i wychodzily w wynikach jako akapity, ktorych nie ma juz
    # w bazie. Zajmowaly miejsce w kazdym wyszukiwaniu i cicho przepadaly
    # dopiero przy skladaniu odpowiedzi.
    _qdrant.delete(
        collection_name=settings.qdrant_collection,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
        ),
    )
    db = SessionLocal()
    try:
        chunks = db.query(Chunk).filter_by(source_id=source_id).order_by(Chunk.id).all()
        if not chunks:
            return 0

        pages = {p.id: p.number for p in db.query(Page).filter_by(source_id=source_id).all()}
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            vectors = embed([c.text for c in batch])
            _qdrant.upsert(
                collection_name=settings.qdrant_collection,
                points=[
                    PointStruct(
                        id=chunk.id,
                        vector=vector,
                        payload={
                            "chunk_id": chunk.id,
                            "source_id": chunk.source_id,
                            "page": pages.get(chunk.page_id),
                        },
                    )
                    for chunk, vector in zip(batch, vectors)
                ],
            )
        return len(chunks)
    finally:
        db.close()


# Slowa, ktore w pytaniu niczego nie zawezaja - wyszukiwanie po nich zwroci
# pol ksiazki.
_STOP = {
    "w", "we", "na", "do", "od", "po", "za", "dla", "przy", "z", "ze", "o", "u",
    "i", "a", "albo", "lub", "czy", "jak", "jaki", "jaka", "jakie", "jakim",
    "kiedy", "gdzie", "ile", "co", "to", "jest", "sa", "byc", "sie", "nie",
    "moge", "mozna", "najlepiej", "lepiej", "powinien", "powinno", "trzeba",
}


def _slowa_kluczowe(pytanie: str) -> list[str]:
    """Slowa z pytania, po ktorych warto szukac doslownie."""
    tokeny = re.findall(r"[\w\u00c0-\u017f]+", pytanie.lower())
    return [t for t in tokeny if len(t) >= 2 and t not in _STOP]


def _wzorzec_calego_slowa(slowo: str) -> str:
    """Wyrazenie dopasowujace cale slowo, nie fragment innego.

    Bez granic slowa "ph" trafialo w "Phytophthora" i akapit o zarazie
    ziemniaczanej wypychal z wynikow ten o odczynie podloza."""
    return r"\m" + re.escape(slowo) + r"\M"


def _szukaj_doslownie(slowa: list[str], source_ids: list[int] | None, limit: int) -> list[int]:
    """Akapity zawierajace slowa z pytania, wazone rzadkoscia slowa.

    Wyszukiwanie wektorowe gubi krotkie, rzadkie terminy: na pytanie "w jakim
    pH najlepiej sadzic pomidory" nie znalazlo akapitu z "odczyn pH 6,0-6,5",
    a zwrocilo temperature i podlewanie. Semantyka rozmywa "pH" wsrod ogolnych
    zdan o uprawie.

    Wazenie jest konieczne, bo samo zliczanie trafien tez nie dziala:
    "pomidory" wystepuje w kazdym akapicie ksiazki o pomidorach i zaglusza
    "pH", ktore jest w pieciu. Slowo rzadkie niesie informacje, slowo czeste
    prawie zadnej - wiec liczy sie odwrotnosc liczby akapitow, w ktorych
    slowo wystepuje.
    """
    if not slowa:
        return []

    db = SessionLocal()
    try:
        wszystkie = db.query(Chunk.id)
        if source_ids:
            wszystkie = wszystkie.filter(Chunk.source_id.in_(source_ids))
        laczna_liczba = wszystkie.count()
        if not laczna_liczba:
            return []

        skladniki = []
        for slowo in slowa:
            wzorzec = _wzorzec_calego_slowa(slowo)
            zapytanie = db.query(Chunk.id).filter(Chunk.text.op("~*")(wzorzec))
            if source_ids:
                zapytanie = zapytanie.filter(Chunk.source_id.in_(source_ids))
            liczba = zapytanie.count()
            if not liczba or liczba > laczna_liczba * 0.5:
                # Slowo nieobecne albo obecne w polowie ksiazki - nic nie wnosi.
                continue
            waga = laczna_liczba / liczba
            skladniki.append(case((Chunk.text.op("~*")(wzorzec), waga), else_=0.0))

        if not skladniki:
            return []

        punkty = sum(skladniki, literal(0.0))
        zapytanie = db.query(Chunk.id, punkty.label("punkty"))
        if source_ids:
            zapytanie = zapytanie.filter(Chunk.source_id.in_(source_ids))
        wiersze = zapytanie.filter(punkty > 0).order_by(punkty.desc(), Chunk.id).limit(limit).all()
        return [w[0] for w in wiersze]
    finally:
        db.close()


# Ile akapitow bierzemy Z KAZDEJ ksiazki osobno.
#
# Pierwsza wersja robila jeden ranking dla calego zbioru i wyrownywala go
# potem. Dzialalo przy dwoch ksiazkach i rozsypywalo sie przy dwunastu: na
# dwanascie miejsc wypadal jeden akapit na ksiazke, a trzy ksiazki nie
# dostawaly nic. Nie da sie tego naprawic mnozeniem regul - jeden wspolny
# ranking zawsze bedzie gral na niekorzysc ksiazek slabszych jezykowo.
#
# Wiec kazda ksiazka jest przeszukiwana osobno i kazda oddaje tyle samo.
# O tym, co z tego wejdzie do odpowiedzi, decyduje pozniej osobny krok.
NA_KSIAZKE = 6


def _zrodla_akapitow(chunk_ids: list[int]) -> dict[int, int]:
    """Ktory akapit z ktorej ksiazki. Przy okazji odsiewa akapity, ktorych juz
    nie ma w bazie - w indeksie moga zostac po starym przetworzeniu."""
    if not chunk_ids:
        return {}
    db = SessionLocal()
    try:
        return {c.id: c.source_id for c in db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()}
    finally:
        db.close()


def szukaj_w_kazdej_ksiazce(
    query: str, source_ids: list[int] | None = None, na_ksiazke: int = NA_KSIAZKE
) -> dict[int, list[int]]:
    """Akapity znalezione OSOBNO w kazdej ksiazce z zakresu.

    Kazda ksiazka dostaje tyle samo miejsca, niezaleznie od tego, ile ich jest
    i ktora wypada lepiej we wspolnym rankingu. Dwie ksiazki czy szescdziesiat
    - zasada ta sama."""
    db = SessionLocal()
    try:
        zapytanie = db.query(Source.id).filter(Source.status == "ready")
        if source_ids:
            zapytanie = zapytanie.filter(Source.id.in_(source_ids))
        ksiazki = [w[0] for w in zapytanie.all()]
    finally:
        db.close()
    if not ksiazki:
        return {}

    # Wektor pytania liczymy RAZ - to jedyny platny krok, reszta to zapytania
    # do Qdranta i Postgresa.
    wektor = embed([query])[0]
    slowa = _slowa_kluczowe(query)

    wynik: dict[int, list[int]] = {}
    for source_id in ksiazki:
        akapity = _szukaj_w_jednej(wektor, slowa, source_id, na_ksiazke)
        if akapity:
            wynik[source_id] = akapity
    return wynik


def _szukaj_w_jednej(wektor: list[float], slowa: list[str], source_id: int, ile: int) -> list[int]:
    """Te same dwa wyszukiwania co zawsze, zawezone do jednej ksiazki."""
    ensure_collection()
    hits = _qdrant.search(
        collection_name=settings.qdrant_collection,
        query_vector=wektor,
        limit=ile * 2,
        query_filter=Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]),
    )
    wektorowe = [hit.payload["chunk_id"] for hit in hits]
    doslowne = _szukaj_doslownie(slowa, [source_id], ile * 2)
    ranking = _polacz(wektorowe, doslowne, ile * 2)
    # Akapity usuniete z bazy zostawaly w indeksie i zajmowaly miejsce.
    istnieja = _zrodla_akapitow(ranking)
    return [c for c in ranking if c in istnieja][:ile]


def _polacz(wektorowe: list[int], doslowne: list[int], limit: int) -> list[int]:
    """Laczy obie listy metoda odwrotnosci pozycji.

    Akapit wysoko na obu listach trafia na gore; taki, ktory jest tylko na
    jednej, nadal ma szanse. Dzieki temu pytanie o "pH" dostaje akapit z
    doslownym "pH", a pytanie opisowe nadal dziala na samej semantyce."""
    punkty: dict[int, float] = {}
    for lista in (wektorowe, doslowne):
        for pozycja, chunk_id in enumerate(lista, start=1):
            punkty[chunk_id] = punkty.get(chunk_id, 0) + 1 / (60 + pozycja)
    return sorted(punkty, key=lambda cid: punkty[cid], reverse=True)[:limit]

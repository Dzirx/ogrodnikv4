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
    FieldCondition,
    Filter,
    MatchAny,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Chunk, Page

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


def search(query: str, source_ids: list[int] | None = None, limit: int = 12) -> list[int]:
    """Zwraca id akapitow pasujacych do pytania.

    `source_ids` to zakres wybrany w rozmowie - jak w NotebookLM redaktor
    zaznacza ksiazki i pyta tylko o nie. Pusta lista albo None oznacza
    wszystkie zrodla.

    Szukamy dwoma sposobami naraz: po znaczeniu (wektory) i po slowach z
    pytania. Same wektory gubily akapity z krotkimi terminami w rodzaju "pH",
    same slowa nie poradzilyby sobie z pytaniem zadanym innymi slowami niz
    ksiazka.

    Limit 12, nie 45 jak w pierwszej wersji: tam szeroki zakres mial nadrobic
    to, ze grounding odsiewal wiekszosc trafien. Tutaj kazdy znaleziony akapit
    idzie do modelu wprost, wiec wiecej znaczy dluzsza i bardziej rozwlekla
    odpowiedz - a redaktor prosil o krotkie."""
    ensure_collection()
    query_filter = None
    if source_ids:
        query_filter = Filter(
            must=[FieldCondition(key="source_id", match=MatchAny(any=list(source_ids)))]
        )
    hits = _qdrant.search(
        collection_name=settings.qdrant_collection,
        query_vector=embed([query])[0],
        limit=limit,
        query_filter=query_filter,
    )
    wektorowe = [hit.payload["chunk_id"] for hit in hits]
    doslowne = _szukaj_doslownie(_slowa_kluczowe(query), source_ids, limit)
    return _polacz(wektorowe, doslowne, limit)

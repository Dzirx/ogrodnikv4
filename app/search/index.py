"""Indeks semantyczny akapitow w Qdrant.

Punkt ma id akapitu, wiec trafienie prowadzi wprost do tekstu, strony i
zrodla - bez tego nie da sie pokazac cytatu ani otworzyc PDF-a na wlasciwej
stronie.
"""

from openai import OpenAI
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


def search(query: str, source_ids: list[int] | None = None, limit: int = 12) -> list[int]:
    """Zwraca id akapitow pasujacych do pytania.

    `source_ids` to zakres wybrany w rozmowie - jak w NotebookLM redaktor
    zaznacza ksiazki i pyta tylko o nie. Pusta lista albo None oznacza
    wszystkie zrodla.

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
    return [hit.payload["chunk_id"] for hit in hits]

"""Pytanie -> odpowiedz zlozona ze zdan, z ktorych kazde wskazuje swoj akapit.

Podzial pracy, odwrotnie niz w pierwszej wersji:

MODEL pisze odpowiedz i przy kazdym zdaniu podaje, z ktorego akapitu je wzial
i ktory fragment to potwierdza. Nie ma slotow podstawianych do tekstu - model
pisze liczby wprost, bo cytat i tak zostanie sprawdzony.

KOD sprawdza jedna rzecz: czy podany cytat naprawde wystepuje w tym akapicie.
Jedno porownanie tekstu, zero kosztu, pewnosc ktorej model nie da. Zdanie,
ktore tego nie przechodzi, zostaje w odpowiedzi, ale jest widocznie oznaczone -
tak jak reszta systemu traktuje rzeczy niepewne, zamiast je po cichu ukrywac.
"""

import json
import re

from openai import OpenAI

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Chunk, Page, Source
from app.search.index import search

_openai = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """Odpowiadasz na pytania o ogrodnictwo wyłącznie na podstawie podanych akapitów ze źródeł.

Pisz po polsku, z pełnymi znakami diakrytycznymi: ą ć ę ł ń ó ś ź ż. Nigdy nie pomijaj ogonków.

Zasady treści:
- Każde zdanie odpowiedzi musi pochodzić z konkretnego akapitu. Podajesz jego "chunk_id" oraz "quote" — dosłowny fragment tego akapitu.
- "quote" musi POTWIERDZAĆ to, co napisałeś w "text". Nie wystarczy, że pochodzi z tego samego akapitu i dotyczy podobnego tematu. Jeśli akapit mówi, że niedobór wapnia przy niskim pH powoduje chorobę, to NIE jest potwierdzenie zdania "pomidor lubi glebę lekko kwaśną" — to zupełnie inna informacja.
- "quote" przepisz znak w znak z akapitu. Nie poprawiaj go, nie skracaj w środku, nie zmieniaj interpunkcji.
- Nie pisz niczego, czego nie ma w akapitach. Zero własnej wiedzy o ogrodnictwie.
- Jeśli akapity nie odpowiadają na pytanie, zwróć pustą listę zdań. To jest poprawna odpowiedź, nie porażka. Wyszukiwanie ZAWSZE zwraca jakieś akapity, nawet gdy żaden nie dotyczy pytania — lepiej powiedzieć "nie mam tego w źródłach" niż zlepić odpowiedź z tekstu o czymś innym.
- Nie wyciągaj wniosków. Jeśli źródło opisuje objawy choroby przy niskim pH, nie przerabiaj tego na zalecenie dotyczące odczynu gleby.

Zasady języka — materiał czytają dorośli, którzy chcą się czegoś dowiedzieć:
- Jedno zdanie = jedna myśl. Zdanie powyżej 20 wyrazów rozbij na dwa.
- Odpowiadaj od razu. Nie zapowiadaj, o czym będziesz pisać, i nie podsumowuj na końcu.
- Zero doklejek bez treści: "co jest korzystne dla środowiska", "co ma istotne znaczenie", "warto pamiętać, że".
- Strona czynna i konkretnie: "rozsadę wysiewa się w drugiej połowie marca", nie "zaleca się rozpoczęcie produkcji rozsady od wysiewu nasion".
- Uważaj na przyimki: "W uprawie gruntowej pomidorów...", nie "Dla uprawy gruntowej pomidorów...".
- Całość do około dziesięciu zdań. Krócej jest lepiej, jeśli odpowiedź jest pełna.

NAJWAŻNIEJSZE: nie przepisuj zdania ze źródła. Źródła są pisane językiem urzędowym ("należy rozpocząć", "zaleca się", "produkcja rozsady") — Ty masz powiedzieć to samo tak, jak powiedziałby człowiek, który się na tym zna i tłumaczy komuś, kto pyta. "quote" ma być dosłownym cytatem ze źródła, ale "text" NIE może być jego kopią ani bliską parafrazą.

Źle:    "Produkcję rozsady pomidorów do uprawy gruntowej należy rozpocząć od wysiewu nasion w drugiej połowie marca."
Dobrze: "Rozsadę na grunt wysiewa się w drugiej połowie marca."

Źle:    "Zaleca się stosowanie podłoża o odczynie lekko kwaśnym."
Dobrze: "Pomidor lubi glebę lekko kwaśną."""


_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "chunk_id": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["text", "chunk_id", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}


def normalize(text: str) -> str:
    """Do porownania cytatu z akapitem.

    Roznice w bialych znakach i rodzaju myslnika nie sa falszerstwem - PDF
    lamie wiersze gdzie popadnie, a model przepisuje z pamieci wzrokowej.
    W pierwszej wersji cytat odrzucany za jeden myslnik byl najczestsza
    przyczyna falszywych alarmow."""
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    text = text.replace(" ", " ").replace("„", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


# Ponizej tej dlugosci "cytat" niczego nie potwierdza - pojedyncze slowo
# znajdzie sie w niemal kazdym akapicie.
MIN_QUOTE_CHARS = 12


def quote_is_in_chunk(quote: str, chunk_text: str) -> bool:
    normalized = normalize(quote)
    if len(normalized) < MIN_QUOTE_CHARS:
        return False
    return normalized in normalize(chunk_text)


def answer_question(question: str, source_ids: list[int] | None = None) -> dict:
    """Zwraca odpowiedz gotowa do pokazania: zdania z cytatami i lista zrodel."""
    chunk_ids = search(question, source_ids=source_ids)
    if not chunk_ids:
        return _no_data()

    db = SessionLocal()
    try:
        chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
        by_id = {c.id: c for c in chunks}
        pages = {p.id: p for p in db.query(Page).filter(Page.id.in_([c.page_id for c in chunks])).all()}
        sources = {s.id: s for s in db.query(Source).filter(Source.id.in_({c.source_id for c in chunks})).all()}

        context = [
            {
                "chunk_id": chunk.id,
                "source": sources[chunk.source_id].title,
                "page": pages[chunk.page_id].number,
                "text": chunk.text,
            }
            # Kolejnosc z wyszukiwania - najtrafniejsze najpierw.
            for chunk in (by_id[cid] for cid in chunk_ids if cid in by_id)
        ]

        raw = _call_model(question, context)
        return _verify(raw, by_id, pages, sources)
    finally:
        db.close()


def _no_data() -> dict:
    """Brak pokrycia w zrodlach.

    Decyzja zapada PRZED wywolaniem modelu - nie polegamy na tym, ze sam powie
    "nie wiem". To jedyna rzecz, ktora odroznia ten program od zwyklego czatu."""
    return {
        "sentences": [],
        "sources": [],
        "note": "Nie mam tego w źródłach. Dodaj książkę albo wklej tekst na ten temat.",
    }


def _call_model(question: str, context: list[dict]) -> dict:
    response = _openai.chat.completions.create(
        model=settings.answer_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps({"pytanie": question, "akapity": context}, ensure_ascii=False),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": _SCHEMA, "strict": True},
        },
    )
    return json.loads(response.choices[0].message.content)


def _verify(raw: dict, by_id: dict, pages: dict, sources: dict) -> dict:
    """Sprawdza kazdy cytat i sklada odpowiedz do pokazania."""
    sentences = []
    used_chunks = []

    for item in raw.get("sentences", []):
        chunk = by_id.get(item.get("chunk_id"))
        if chunk is None:
            # Model wskazal akapit, ktorego mu nie dalismy.
            sentences.append({"text": item.get("text", ""), "verified": False, "source": None})
            continue

        verified = quote_is_in_chunk(item.get("quote", ""), chunk.text)
        page = pages[chunk.page_id]
        source = sources[chunk.source_id]
        if chunk.id not in used_chunks:
            used_chunks.append(chunk.id)

        sentences.append(
            {
                "text": item.get("text", ""),
                "verified": verified,
                "source": {
                    "chunk_id": chunk.id,
                    "source_id": source.id,
                    "source_title": source.title,
                    "source_kind": source.kind,
                    "page": page.number,
                    "quote": item.get("quote", ""),
                    "marker": used_chunks.index(chunk.id) + 1,
                },
            }
        )

    if not sentences:
        return _no_data()

    source_list = []
    for index, chunk_id in enumerate(used_chunks, start=1):
        chunk = by_id[chunk_id]
        source_list.append(
            {
                "marker": index,
                "chunk_id": chunk_id,
                "source_id": chunk.source_id,
                "source_title": sources[chunk.source_id].title,
                "source_kind": sources[chunk.source_id].kind,
                "page": pages[chunk.page_id].number,
                "text": chunk.text,
            }
        )

    return {"sentences": sentences, "sources": source_list, "note": None}

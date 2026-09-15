"""Przeglad zrodla zaraz po wgraniu: program sam pyta i sam znajduje roznice.

Redaktor ma wgrac ksiazke i dostac gotowa liste rzeczy do rozstrzygniecia.
Nie ma wpisywac pytan po to, zeby program zaczal porownywac - to bylaby ta sama
praca, ktora mial przejac.

Pytania nie sa wpisane na sztywno. Klient zapowiada szescdziesiat warzyw, wiec
lista tematow dla pomidora zestarzalaby sie przy pierwszej ksiazce o kapuscie.
Model czyta probke ksiazki i sam mowi, o czym ona jest - a potem kazdy z tych
tematow idzie ta sama droga co pytanie zadane recznie.
"""

import json

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Chunk, Source

_openai = OpenAI(api_key=settings.openai_api_key)

# Ile pytan zadajemy jednej ksiazce. Kazde kosztuje wyszukiwanie i wywolanie
# modelu, wiec to swiadomy sufit, nie przypadek.
ILE_PYTAN = 12

# Ile akapitow pokazujemy modelowi, zeby powiedzial, o czym jest ksiazka.
PROBKA = 40

TEMATY_PROMPT = """Dostajesz próbkę akapitów z książki ogrodniczej. Wypisz pytania, które
ogrodnik-praktyk zadałby tej książce.

Zasady:
- Pytanie musi dotyczyć rzeczy, o której książka pisze konkretnie: wartości, terminu,
  sposobu postępowania. Nie pytaj o rzeczy ogólne ani o filozofię uprawy.
- W każdym pytaniu nazwij roślinę albo rzecz, której dotyczy. "W jakim odczynie gleby?"
  jest bezużyteczne, "W jakim odczynie gleby sadzić pomidory?" nie.
- Pytaj o to, co da się porównać między książkami: odczyn, termin, temperatura,
  rozstaw, głębokość, częstotliwość, dawka, odmiana.
- Każde pytanie o coś innego. Nie powtarzaj tego samego innymi słowami."""

_SCHEMA = {
    "type": "object",
    "properties": {"pytania": {"type": "array", "items": {"type": "string"}}},
    "required": ["pytania"],
    "additionalProperties": False,
}


def pytania_do_zrodla(db: Session, source: Source) -> list[str]:
    """O co warto zapytac te ksiazke - na podstawie jej wlasnej tresci."""
    akapity = (
        db.query(Chunk)
        .filter_by(source_id=source.id)
        .order_by(Chunk.id)
        .limit(PROBKA * 4)
        .all()
    )
    if not akapity:
        return []
    # Probka rozlozona po calej ksiazce, nie pierwsze czterdziesci akapitow -
    # poczatek to zwykle wstep i spis tresci.
    krok = max(len(akapity) // PROBKA, 1)
    probka = [c.text for c in akapity[::krok]][:PROBKA]

    etykiety = [e.name for e in source.labels]
    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": TEMATY_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tytul": source.title,
                            "tematy": etykiety,
                            "ile_pytan": ILE_PYTAN,
                            "akapity": probka,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "tematy", "schema": _SCHEMA, "strict": True}},
        )
        pytania = json.loads(odpowiedz.choices[0].message.content).get("pytania", [])
    except Exception:
        return []
    return [p.strip() for p in pytania if p and p.strip()][:ILE_PYTAN]


def przejrzyj_zrodlo(source_id: int) -> int:
    """Przepuszcza nowa ksiazke przez jej wlasne pytania i szuka roznic.

    Szukamy w CALYM zbiorze, nie tylko w nowej ksiazce: roznica powstaje miedzy
    ksiazkami, wiec nowa musi zostac zestawiona z tym, co mowia pozostale.

    Zwraca liczbe znalezionych roznic."""
    from app.answer.build import zbierz_fakty_do_pytania
    from app.answer.konflikty import znajdz_konflikty

    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        if source is None:
            return 0
        # Jedna ksiazka nie ma sie z czym roznic - przeglad odpalamy dopiero,
        # gdy jest z czym porownywac.
        if db.query(Source).filter_by(status="ready").count() < 2:
            return 0

        znalezione = 0
        for pytanie in pytania_do_zrodla(db, source):
            try:
                fakty, by_id = zbierz_fakty_do_pytania(db, pytanie)
                if fakty:
                    znalezione += len(znajdz_konflikty(db, pytanie, fakty, by_id))
            except Exception:
                # Jedno pytanie, ktore sie nie udalo, nie moze przerwac przegladu
                # calej ksiazki.
                continue
        return znalezione
    finally:
        db.close()

"""Plan zagadnien dla dluzszego tekstu.

Bez planu program robil jedno wyszukiwanie na cale polecenie: "sadzenie
pomidorow w tunelach" dawalo 28 akapitow i z tego mial powstac artykul. Stad
brala sie wata - model dostawal za malo materialu i rozciagal to, co mial.

Plan zmienia pytanie z "wez wiecej faktow" na "zbierz material". Model wypisuje
zagadnienia, ktore taki tekst powinien obejmowac, a program szuka OSOBNO dla
kazdego. Zagadnienie bez pokrycia w ksiazkach wypada po cichu - plan powstaje
z wiedzy modelu, wiec zaplanuje tez rzeczy, ktorych zrodla nie maja.
"""

import json

from openai import OpenAI

from app.config import settings

_openai = OpenAI(api_key=settings.openai_api_key)

# Ile zagadnien ma sens. Kazde to osobne wyszukiwanie w kazdej ksiazce - tanie,
# bo bez modelu, ale nie za darmo.
MAX_ZAGADNIEN = 7

PLAN_PROMPT = """Dostajesz polecenie i formę tekstu, który ma powstać. Wypisz zagadnienia,
które ten tekst powinien obejmować.

Zasady:
- Zagadnienie to rzecz do opisania, nie nagłówek do wypełnienia: "ile i czym podlewać",
  "podlewanie w upały", "podlewanie roślin w pojemnikach", "najczęstsze błędy".
- Każde o czym innym. Nie rozbijaj jednej rzeczy na trzy bliskoznaczne.
- Zagadnienia posłużą do szukania w książkach ogrodniczych, więc nazywaj je tak, jak
  nazwałaby je książka — konkretnie, z nazwą rośliny albo czynności.
- Kolejność ma być kolejnością tekstu: od przygotowania, przez prowadzenie, po kłopoty.
- Tyle zagadnień, ile temat naprawdę ma. Przy wąskim poleceniu wystarczą dwa."""

_SCHEMA = {
    "type": "object",
    "properties": {"zagadnienia": {"type": "array", "items": {"type": "string"}}},
    "required": ["zagadnienia"],
    "additionalProperties": False,
}


def zaplanuj(pytanie: str, forma: str) -> list[str]:
    """Zagadnienia do opisania. Pusta lista, gdy tekst jest krotki."""
    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": PLAN_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"polecenie": pytanie, "forma": forma, "ile_najwyzej": MAX_ZAGADNIEN},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "plan", "schema": _SCHEMA, "strict": True}},
        )
        zagadnienia = json.loads(odpowiedz.choices[0].message.content).get("zagadnienia", [])
    except Exception:
        # Bez planu tekst i tak powstanie - z jednego wyszukiwania, jak dotad.
        return []
    return [z.strip() for z in zagadnienia if z and z.strip()][:MAX_ZAGADNIEN]

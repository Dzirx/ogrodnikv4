"""Kontrola gotowego tekstu: czy twierdzenia wynikaja z faktow.

Do tej pory kod sprawdzal jedna rzecz - czy cytat stoi w podanym akapicie. To
zostaje jako podloga, bo jest deterministyczne. Ale nie odpowiada na pytanie,
czy ZDANIE wynika z tego, co cytat mowi, ani czy zachowuje jego warunek.

Bez tej odpowiedzi jedyna obrona przed zmyslonym zaleceniem bylo zadanie
przypisu przy kazdym kawalku - a wtedy tekst czyta sie jak lista faktow, bo
model nie ma jak napisac przejscia ani zdania wprowadzajacego.

Kontrola przenosi gwarancje we wlasciwe miejsce: z "kazde zdanie ma cytat" na
"zadne zdanie nie twierdzi niczego spoza ksiazek". Zdanie, ktore niczego nie
twierdzi ("Przejdzmy teraz do podlewania"), przechodzi bez przypisu. Zdanie,
ktore twierdzi cos, czego w faktach nie ma, wypada.

Uwaga co do zakresu: to jest ocena modelu i moze sie mylic. Nie jest gwarancja
prawdziwosci - wylapuje dopisane zalecenia, zgubione warunki i uzasadnienia bez
pokrycia. Dlatego sprawdzenie cytatu zostaje i dziala niezaleznie.
"""

import json

from openai import OpenAI

from app.config import settings

_openai = OpenAI(api_key=settings.openai_api_key)

KONTROLA_PROMPT = """Dostajesz zdania gotowego tekstu ogrodniczego. Przy każdym stoją fakty
wypisane z książek, na których to zdanie miało stanąć. Sprawdź każde osobno.

"twierdzi" — czy zdanie mówi coś o uprawie: podaje wartość, zalecenie, przyczynę, ocenę.
- "Przejdźmy teraz do podlewania" nie twierdzi niczego. Fałsz.
- "Kiedy rozsada jest już w ziemi, zaczyna się właściwa robota" nie twierdzi niczego. Fałsz.
- "W tunelu wszystko rośnie szybciej niż w gruncie" TWIERDZI. To uogólnienie wymagające
  pokrycia, nie ozdobnik.
- Każde zdanie z liczbą, terminem, dawką albo poleceniem twierdzi.

"wynika" — czy to, co zdanie mówi, wynika z podanych przy nim faktów. Fałsz, gdy zdanie
dodaje przyczynę, skutek albo zalecenie, którego w faktach nie ma — nawet jeśli to prawda.
Przy zdaniu, które niczego nie twierdzi, wpisz prawdę.

"warunek" — czy zdanie zachowuje warunek z faktu. Fakt "pod osłonami podlewać częściej"
zamieniony na "podlewaj częściej" gubi warunek i wprowadza w błąd. Fałsz.

"co_nie_pasuje" — jednym zdaniem, co konkretnie nie wynika z faktów. Pusty napis, gdy
wszystko w porządku.

Oceniaj samo zdanie wobec samych faktów. Nie dopowiadaj z własnej wiedzy o ogrodnictwie —
zdanie prawdziwe, ale niewynikające z faktów, ma dostać "wynika": fałsz."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "zdania": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nr": {"type": "integer"},
                    "twierdzi": {"type": "boolean"},
                    "wynika": {"type": "boolean"},
                    "warunek": {"type": "boolean"},
                    "co_nie_pasuje": {"type": "string"},
                },
                "required": ["nr", "twierdzi", "wynika", "warunek", "co_nie_pasuje"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["zdania"],
    "additionalProperties": False,
}


def sprawdz_zdania(zdania: list[dict]) -> dict[int, dict]:
    """Ocena kazdego zdania wobec faktow, na ktorych stoi.

    `zdania` to lista {"nr", "tekst", "fakty": [tresc faktu, ...]}.
    Zwraca mape numer -> ocena. Gdy wywolanie padnie, mapa jest pusta i tekst
    zostaje taki, jaki byl - kontrola nie moze zabrac odpowiedzi."""
    if not zdania:
        return {}
    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": KONTROLA_PROMPT},
                {"role": "user", "content": json.dumps({"zdania": zdania}, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "kontrola", "schema": _SCHEMA, "strict": True}},
        )
        oceny = json.loads(odpowiedz.choices[0].message.content).get("zdania", [])
    except Exception:
        return {}
    return {o["nr"]: o for o in oceny if isinstance(o.get("nr"), int)}


def do_usuniecia(ocena: dict) -> bool:
    """Czy zdanie wypada z tekstu.

    Decyzja kodu, nie modelu: wypada zdanie, ktore COS TWIERDZI i albo nie
    wynika z faktow, albo gubi ich warunek. Zdanie, ktore niczego nie twierdzi,
    zostaje - i o to chodzilo, zeby tekst mogl miec przejscia."""
    if not ocena.get("twierdzi"):
        return False
    return not ocena.get("wynika", True) or not ocena.get("warunek", True)

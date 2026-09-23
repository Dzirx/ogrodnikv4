"""Tabele z warstwy tekstowej PDF. Patrz docs/tabele.md.

`page.get_text()` czyta tabele wierszami i rozrywa je na kawalki - naglowek
"Dawka na ha" ląduje o kilkaset znakow od wartosci, ktorej dotyczy. Dwa
wywolania modelu na strone naprawiaja to bez jednej linijki kodu, ktora
sklada albo sprawdza tresc:

Model 1 czyta tabele z obrazu i tekstu warstwy naraz - obraz mowi, co z czym
sasiaduje, tekst mowi, jak sie to pisze. Model 2 dostaje ten sam obraz i wynik
modelu 1, poprawia pomylki (kolumny, zmyslone naglowki, pasek sekcji wzięty za
wartosc) i zapisuje blok czytelnym tekstem.

Kod nie sprawdza wartosci - kazda kontrola, jaka napisalem, mylila sie
czesciej niz model (patrz "Dlaczego kod nie sprawdza wartosci" w docs). Blad,
ktory oba modele przepuszcza, wejdzie do bazy."""

import base64
import json

from openai import OpenAI

from app.config import settings
from app.ingest.ocr import zrzut_strony

_openai = OpenAI(api_key=settings.openai_api_key)

# Ponizej tylu wierszy to nie tabela, tylko ramka wokol zdjecia albo dwie
# podpisane obok siebie fotografie - PyMuPDF widzi pionowa kreske miedzy nimi
# i zglasza tabele 1x2. Zmierzone na broszurze PODR (_tab/): strony 6-9 maja
# dokladnie taki uklad i nie sa tabela, strona 10 (13 wierszy) jest.
#
# Liczba kolumn celowo NIE jest tu progiem. Pierwsza wersja odrzucala strony
# z wiecej niz 12 kolumnami - i odrzucala tez prawdziwe tabele dawek (program
# ochrony pomidora, str. 21-24), bo PyMuPDF czasem dzieli te sama 9-kolumnowa
# tabele na 23-27 przez szum w liniach siatki. Kolumny liczy sie tu tylko po
# to, zeby zdecydowac "tabela czy nie" - tresc i tak czyta model patrzacy
# na obraz, wiec bledny podzial na kolumny w tym miejscu nic nie kosztuje.
MIN_WIERSZY = 2


def _prawdziwa_tabela(wiersze: list[list[str | None]]) -> bool:
    """Odsiewa fałszywe wykrycia PyMuPDF - ramkę albo pojedynczy podpis wzięty za tabelę."""
    if len(wiersze) < MIN_WIERSZY:
        return False
    return any((k or "").strip() for w in wiersze for k in w)


def czy_tabela(strona) -> bool:
    """Czy strona ma prawdziwa tabele - wykrywana z kresek w PDF-ie, nie z tresci.

    Tabele fotografowane (bez warstwy tekstowej) nie trafiaja tu wcale - ten
    sam brak warstwy kieruje strone do OCR-u (app.ingest.ocr), a tabel z OCR-u
    świadomie nie obsługujemy (patrz "Czego nie robimy" w docs)."""
    try:
        tabele = strona.find_tables(strategy="lines").tables
    except Exception:
        return False
    return any(_prawdziwa_tabela(t.extract()) for t in tabele)


_SCHEMA_ODCZYT = {
    "type": "object",
    "properties": {
        "naglowki": {"type": "array", "items": {"type": "string"}},
        "wiersze": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"komorki": {"type": "array", "items": {"type": ["string", "null"]}}},
                "required": ["komorki"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["naglowki", "wiersze"],
    "additionalProperties": False,
}

ODCZYT_PROMPT = (
    "Odczytaj tabelę z obrazu. Nazwy kolumn weź z tabeli. Wartości przepisz dokładnie "
    "z tekstu poniżej. Komórka scalona z wierszem wyżej = null.\n\nTEKST STRONY:\n"
)

_SCHEMA_POPRAWKA = {
    "type": "object",
    "properties": {"poprawki": {"type": "string"}, "blok": {"type": "string"}},
    "required": ["poprawki", "blok"],
    "additionalProperties": False,
}

POPRAWKA_PROMPT = """Inny model odczytał tę tabelę z obrazu; jego wynik masz niżej. Może zawierać błędy:
pomylone kolumny, wymyślone nazwy nagłówków, pasek sekcji wzięty za wartość.

POPRAW je, patrząc na obraz, i zapisz zawartość tabeli czytelnym tekstem: po jednym wpisie
na środek, z nazwami kolumn przy wartościach. Nazwy kolumn bierz z tabeli; jeśli na tej
stronie ich nie ma, nie wymyślaj - pisz "kolumna 1", "kolumna 2". Komórkę scaloną z wierszem
wyżej zapisz jako "(jak wyżej)". Nie dodawaj nic spoza tabeli.

W polu "poprawki" wypisz po polsku, co zmieniłeś wobec odczytu niżej.

ODCZYT:
"""


def _obraz(strona) -> dict:
    png = zrzut_strony(strona)
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode(), "detail": "high"},
    }


def odczytaj_tabele(strona, tekst: str) -> str:
    """Blok czytelnego tekstu z tabeli tej strony - jeden Chunk, nie zdanie na wiersz.

    Model piszący odpowiedź radzi sobie z całym blokiem lepiej niż z rozbitymi
    zdaniami (patrz "Dlaczego blok, a nie osobne zdania" w docs) - dlatego
    kod nie dzieli wyniku i nie przepuszcza go przez split_into_paragraphs.

    Gdy któreś wywołanie padnie, zostaje zwykły odczyt warstwy tekstowej -
    gorszy, poszarpany akapit jest lepszy niż strona bez treści."""
    obraz = _obraz(strona)
    try:
        odczyt = _openai.chat.completions.create(
            model=settings.answer_model,
            temperature=0,
            messages=[{"role": "user", "content": [{"type": "text", "text": ODCZYT_PROMPT + tekst}, obraz]}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "tabela", "schema": _SCHEMA_ODCZYT, "strict": True},
            },
        )
        w1 = json.loads(odczyt.choices[0].message.content)

        poprawka = _openai.chat.completions.create(
            model=settings.answer_model,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": POPRAWKA_PROMPT + json.dumps(w1, ensure_ascii=False)},
                        obraz,
                    ],
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "poprawka", "schema": _SCHEMA_POPRAWKA, "strict": True},
            },
        )
        blok = json.loads(poprawka.choices[0].message.content).get("blok", "").strip()
    except Exception:
        return tekst

    return blok or tekst

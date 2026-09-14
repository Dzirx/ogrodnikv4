"""Deterministyczna kontrola jezyka odpowiedzi.

Klient czyta teksty uchem człowieka starszej daty i natychmiast wyłapuje
zdania urzędowe: "zalecane podłoże ma pH", "należy monitorować temperaturę".
Prompt prosi model, żeby tak nie pisał, ale prośba to nie gwarancja - tak samo
jak przy cytatach, gdzie prośba o dosłowność nie wystarcza i sprawdza to kod.

Ten moduł nie ocenia, czy zdanie jest ładne. Sprawdza konkretne, policzalne
rzeczy: długość i obecność zwrotów, które w polszczyźnie zawsze brzmią
urzędowo.

Wskaźnik mglistości Gunninga, o który pytał klient, celowo NIE jest tu użyty:
liczy słowa trzysylabowe jako trudne, a po polsku taka jest większość
słownictwa - poprawne zdanie dostawałoby alarmujący wynik.
"""

import re

# Powyżej tylu wyrazów zdanie przestaje być jedną myślą. Osiemnaście, nie
# dwadzieścia pięć: to odpowiedź na pytanie, nie rozdział książki.
MAX_WYRAZOW = 18

_URZEDOWE = [
    (re.compile(r"\bzaleca\s+się\b", re.I), "zaleca się"),
    (re.compile(r"\bzalecan[ey]\b", re.I), "zalecane"),
    (re.compile(r"\bnależy\b", re.I), "należy"),
    (re.compile(r"\bpowin(no|ien|na|ny)\b", re.I), "powinien/powinno (zamiast: ma być, jest)"),
    (re.compile(r"\bwskazane\s+jest\b", re.I), "wskazane jest"),
    (re.compile(r"\brekomenduje\s+się\b", re.I), "rekomenduje się"),
    (re.compile(r"\bstosowanie\b", re.I), "stosowanie (zamiast: stosuje się)"),
    (re.compile(r"\bprodukcj[aeię]\s+rozsady\b", re.I), "produkcja rozsady (zamiast: rozsadę produkuje się)"),
    (re.compile(r"\bmonitorowa[ćc]\b", re.I), "monitorować (zamiast: pilnuj)"),
    # Słowa z języka opracowań fachowych. Ogrodnik powie "lubi", nie "preferuje".
    (re.compile(r"\bpreferuj[ea]\b", re.I), "preferuje (zamiast: lubi)"),
    (re.compile(r"\b(charakteryzuje|cechuje)\s+się\b", re.I), "charakteryzuje się"),
    (re.compile(r"\bw\s+przypadku\b", re.I), "w przypadku (zamiast: przy, gdy)"),
    (re.compile(r"\bzapewni[ćc]\s+odpowiedni", re.I), "zapewnić odpowiednie (zamiast: zadbać o)"),
]

# Doklejki, które nic nie wnoszą - wprost z uwag klienta do pierwszej wersji.
_DOKLEJKI = [
    (re.compile(r",\s*co\s+jest\s+korzystne\b", re.I), "co jest korzystne..."),
    (re.compile(r",\s*co\s+ma\s+istotne\s+znaczenie\b", re.I), "co ma istotne znaczenie"),
    (re.compile(r"^\s*(warto|należy)\s+pamiętać\b", re.I), "warto pamiętać"),
    (re.compile(r"^\s*podsumowując\b", re.I), "podsumowując"),
    (re.compile(r"\bkluczow(ym|e)\s+(elementem|jest)\b", re.I), "kluczowym elementem"),
    (re.compile(r"\bistotne\s+jest\b", re.I), "istotne jest"),
    (re.compile(r"\bw\s+dzisiejszych\s+czasach\b", re.I), "w dzisiejszych czasach"),
    (re.compile(r"^\s*(po\s+pierwsze|dodatkowo|ponadto|co\s+więcej)\b", re.I), "łącznik na początku zdania"),
]

# "Dla uprawy gruntowej..." zamiast "W uprawie gruntowej..." - zdanie wskazane
# przez klienta jako niepoprawne po polsku.
_PRZYIMEK = re.compile(r"\bdla\s+(uprawy|siewu|wysiewu|sadzenia|nawożenia|podlewania)\b", re.I)


def policz_wyrazy(zdanie: str) -> int:
    """Liczba wyrazów. Liczba z przecinkiem ("6,0") albo zakres ("6,0-6,5") to
    jeden wyraz - inaczej zdanie z kilkoma wartościami wychodziłoby sztucznie
    długie i bramka zgłaszałaby fałszywy alarm."""
    return len(re.findall(r"\d+(?:[.,]\d+)*(?:[-–]\d+(?:[.,]\d+)*)?|[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ-]+", zdanie))


def sprawdz_odpowiedz(zdania: list[str]) -> dict[int, list[str]]:
    """Uwagi do calej odpowiedzi - to, czego nie widac w pojedynczym zdaniu.

    Dwa zdania pod rzad zaczynajace sie tak samo ("Jesli... Jesli...") to
    wyliczanka faktow, nie wypowiedz. Model dostaje fakty jeden po drugim i
    bez takiej kontroli opakowuje kazdy w osobne zdanie warunkowe."""
    uwagi: dict[int, list[str]] = {}
    for i in range(1, len(zdania)):
        poprzednie = _pierwsze_slowo(zdania[i - 1])
        biezace = _pierwsze_slowo(zdania[i])
        if poprzednie and poprzednie == biezace:
            uwagi.setdefault(i, []).append(f'zdanie zaczyna się tak samo jak poprzednie ("{biezace}")')
    return uwagi


def _pierwsze_slowo(zdanie: str) -> str:
    slowa = re.findall(r"[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", zdanie)
    return slowa[0].lower() if slowa else ""


def sprawdz(zdanie: str) -> list[str]:
    """Zwraca listę uwag do zdania. Pusta lista = zdanie brzmi naturalnie."""
    uwagi = []

    wyrazy = policz_wyrazy(zdanie)
    if wyrazy > MAX_WYRAZOW:
        uwagi.append(f"zdanie ma {wyrazy} wyrazów (limit {MAX_WYRAZOW})")

    for wzorzec, nazwa in _URZEDOWE:
        if wzorzec.search(zdanie):
            uwagi.append(f"urzędowy zwrot: {nazwa}")

    for wzorzec, nazwa in _DOKLEJKI:
        if wzorzec.search(zdanie):
            uwagi.append(f"doklejka bez treści: {nazwa}")

    if _PRZYIMEK.search(zdanie):
        uwagi.append('"Dla uprawy..." zamiast "W uprawie..."')

    return uwagi

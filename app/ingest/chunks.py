"""Podzial tekstu na akapity.

Akapit jest jednostka wszystkiego: wyszukiwania, cytowania i podgladu. Nie ma
tu heurystyki naglowkow ani odtwarzania struktury rozdzialow - pierwsza wersja
to miala i nie wplywalo to na ani jeden cytat, za to produkowalo zadania w
kolejce, przy ktorych nie dalo sie nic zrobic.

Ksiazki roznia sie tym, jak wychodza z PDF-a. Czesc ma puste linie miedzy
akapitami, czesc (np. "Pomidory - uprawa amatorska w ogrodzie") nie ma ich
wcale - tam cala strona wychodzi jako jeden ciag z pojedynczymi zlamaniami
wiersza. Dlatego podzial ma dwa etapy: najpierw po pustych liniach, potem
zbyt dlugie kawalki po zdaniach.
"""

import re

# Ponizej tego progu akapit nie niesie tresci nadajacej sie do zacytowania
# (numer strony, urwana linia, podpis pod rysunkiem).
#
# 40, nie wiecej: "Nasiona najszybciej kielkuja w temperaturze 22-28 C" ma 51
# znakow i jest dokladnie tym, czego szukamy. Prog 60 odsialby taki akapit.
MIN_CHARS = 40

# Gorna granica akapitu. Powyzej niej cytat przestaje wskazywac konkretne
# miejsce, a podglad strony traci sens - redaktor dostaje "gdzies tutaj".
# 700 znakow to mniej wiecej cztery, piec zdan.
MAX_CHARS = 700

# Linia spisu tresci: "6.8. Odchwaszczanie . . . . . . . 65". W pierwszej wersji
# takie linie szly do modelu i wracaly jako twierdzenia "Spis tresci".
_TOC_RE = re.compile(r"\.{4,}\s*\d+\s*$|(\.\s){4,}")

# Koniec zdania: kropka, wykrzyknik lub pytajnik, po ktorym idzie spacja i
# wielka litera. Skroty ("np.", "ok.") nie pasuja, bo po nich idzie mala.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])")


def looks_like_noise(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return True
    if _TOC_RE.search(stripped):
        return True
    # Sama liczba albo numer strony.
    if re.fullmatch(r"[\d\s\-–.]+", stripped):
        return True
    return False


def _join_lines(text: str) -> str:
    """Skleja przeniesienia wyrazow i pojedyncze zlamania wiersza.

    "wypeł-\\nnione" w PDF-ie to jedno slowo zlamane na dwie linie. Bez
    sklejenia cytat modelu nigdy nie zgodzi sie ze zrodlem - w pierwszej wersji
    to byla najczestsza przyczyna falszywych odrzucen."""
    text = re.sub(r"(\w)[-­]\s*\n\s*(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_long(text: str) -> list[str]:
    """Dzieli zbyt dlugi kawalek po granicach zdan.

    Nigdy w polowie zdania: cytat ma byc czytelny dla czlowieka, ktory go
    zobaczy w podgladzie, a nie tylko dopasowalny maszynowo."""
    if len(text) <= MAX_CHARS:
        return [text]

    parts: list[str] = []
    biezacy = ""
    for zdanie in _SENTENCE_END_RE.split(text):
        if biezacy and len(biezacy) + len(zdanie) + 1 > MAX_CHARS:
            parts.append(biezacy.strip())
            biezacy = zdanie
        else:
            biezacy = f"{biezacy} {zdanie}".strip()
    if biezacy.strip():
        parts.append(biezacy.strip())
    return parts


def split_into_paragraphs(text: str) -> list[str]:
    if not text:
        return []

    paragraphs = []
    for blok in re.split(r"\n\s*\n", text):
        sklejony = _join_lines(blok)
        if not sklejony:
            continue
        for kawalek in _split_long(sklejony):
            if not looks_like_noise(kawalek):
                paragraphs.append(kawalek)
    return paragraphs

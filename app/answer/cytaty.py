"""Sprawdzenie cytatu - jedyna bramka, ktora trzyma kod.

Osobny modul, bo korzysta z niej i pisanie odpowiedzi, i szukanie roznic
miedzy ksiazkami. Trzymanie jej w build.py robilo zapetlony import."""

import re

# Ponizej tej dlugosci "cytat" niczego nie potwierdza - pojedyncze slowo
# znajdzie sie w niemal kazdym akapicie.
MIN_QUOTE_CHARS = 12


def normalize(text: str) -> str:
    """Do porownania cytatu z akapitem.

    Roznice w bialych znakach i rodzaju myslnika nie sa falszerstwem - PDF
    lamie wiersze gdzie popadnie, a model przepisuje z pamieci wzrokowej.
    W pierwszej wersji cytat odrzucany za jeden myslnik byl najczestsza
    przyczyna falszywych alarmow."""
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    text = text.replace(" ", " ").replace("„", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def bez_odstepow(text: str) -> str:
    """Sam ciag liter, bez zadnych bialych znakow.

    PDF lamie wyrazy na granicy wiersza, czasem bez myslnika - "doklad\nnie"
    zostaje jako "doklad nie". Model czyta to jako jedno slowo i ma racje,
    wiec porownanie po samych literach jest blizsze prawdzie niz porownanie
    ze spacjami. Podmiana liczby albo dopisane slowo nadal nie przejda."""
    return re.sub(r"\s+", "", normalize(text))


def quote_is_in_chunk(quote: str, chunk_text: str) -> bool:
    normalized = normalize(quote)
    if len(normalized) < MIN_QUOTE_CHARS:
        return False
    if normalized in normalize(chunk_text):
        return True
    return bez_odstepow(quote) in bez_odstepow(chunk_text)

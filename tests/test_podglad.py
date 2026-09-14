"""Zaznaczanie cytatu na stronie zrodla."""

import fitz

from app.ingest.podglad import _dopasuj_slowa, _normalizuj, render_strony


def _pdf_z_tekstem(tekst: str) -> bytes:
    dokument = fitz.open()
    strona = dokument.new_page()
    strona.insert_text((72, 100), tekst, fontsize=11)
    return dokument.tobytes()


def test_normalizacja_zdejmuje_interpunkcje():
    assert _normalizuj("marca,") == "marca"
    assert _normalizuj("22–28°C") == "2228c"


def test_znajduje_slowa_cytatu():
    strona = "rozsade na grunt wysiewa sie w drugiej polowie marca a potem sadzi".split()
    cytat = "wysiewa sie w drugiej polowie marca".split()
    assert _dopasuj_slowa(strona, cytat) == [3, 4, 5, 6, 7, 8]


def test_pomija_slowa_spoza_cytatu():
    """Na marginesie ksiazki biegnie pionowy tytul rozdzialu, ktorego slowa
    PyMuPDF wplata w kolejnosc czytania. Zaznaczanie calego zakresu braloby je
    razem z trescia - redaktor widzialby zolty pasek przez pol strony."""
    strona = "rozsade na DOMOWA grunt PRODUKCJA wysiewa sie w marcu".split()
    cytat = "rozsade na grunt wysiewa sie w marcu".split()

    indeksy = _dopasuj_slowa(strona, cytat)

    assert 2 not in indeksy  # DOMOWA
    assert 4 not in indeksy  # PRODUKCJA
    assert indeksy == [0, 1, 3, 5, 6, 7, 8]


def test_nie_zaznacza_gdy_pokrycie_za_male():
    """Lepiej nie zaznaczyc nic niz wskazac zly akapit. Fraza "wysiewu nasion"
    trafia w kilka miejsc strony - przy szukaniu osobnych kawalkow redaktor
    dostawal pol strony na zolto zamiast jednego wskazanego miejsca."""
    strona = "zupelnie inny tekst o czym innym na tej stronie".split()
    cytat = "rozsade na grunt wysiewa sie w drugiej polowie marca".split()
    assert _dopasuj_slowa(strona, cytat) == []


def test_renderuje_strone_jako_png():
    obraz = render_strony(_pdf_z_tekstem("Rozsade wysiewa sie w marcu."), 1, "Rozsade wysiewa sie")
    assert obraz[:8] == b"\x89PNG\r\n\x1a\n"


def test_nieistniejaca_strona_daje_blad():
    import pytest

    with pytest.raises(ValueError):
        render_strony(_pdf_z_tekstem("cokolwiek"), 99)

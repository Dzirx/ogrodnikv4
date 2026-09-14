"""Podświetlanie cytatu w tekście akapitu.

Rysowanie na obrazie strony okazało się zawodne: współrzędne z odczytu tekstu
i z renderu rozjeżdżają się w niektórych PDF-ach o całą linijkę, więc żółta
ramka lądowała przy sąsiednim zdaniu i myliła bardziej, niż pomagała.
W tekście nie ma żadnych układów współrzędnych do pomylenia.
"""

from app.api.routes import _rozbij_na_cytat

AKAPIT = "Niedobór wapnia przy niskim pH. Jak zapobiegać: Podnieś pH gleby do około 6,0. Nawożenie wapniem: opryskuj rośliny."


def test_dzieli_akapit_na_trzy_czesci():
    czesci = _rozbij_na_cytat(AKAPIT, "Podnieś pH gleby do około 6,0.")

    assert len(czesci) == 3
    assert czesci[1]["cytat"] is True
    assert "Podnieś pH gleby" in czesci[1]["tekst"]
    assert czesci[0]["cytat"] is False and czesci[2]["cytat"] is False


def test_cytat_na_poczatku_nie_tworzy_pustej_czesci():
    czesci = _rozbij_na_cytat(AKAPIT, "Niedobór wapnia przy niskim pH.")
    assert czesci[0]["cytat"] is True


def test_rozne_biale_znaki_nie_psuja_dopasowania():
    """Model przepisuje cytat z PDF-a, który łamie wiersze gdzie popadnie."""
    czesci = _rozbij_na_cytat(AKAPIT, "Podnieś   pH\ngleby do około 6,0.")
    assert any(c["cytat"] for c in czesci)


def test_cytat_spoza_akapitu_zostawia_tekst_bez_zmian():
    czesci = _rozbij_na_cytat(AKAPIT, "zupełnie inne zdanie z innej książki")
    assert len(czesci) == 1
    assert czesci[0]["cytat"] is False


def test_brak_cytatu_zwraca_caly_akapit():
    assert _rozbij_na_cytat(AKAPIT, "") == [{"tekst": AKAPIT, "cytat": False}]

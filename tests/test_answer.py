"""Weryfikacja cytatow - jedyna bramka, ktora trzyma kod.

Model pisze, kod sprawdza czy cytat naprawde jest w akapicie. Reguly
normalizacji pochodza wprost z bledow pierwszej wersji: tam cytat odrzucony
za jeden mysnik byl najczestsza przyczyna falszywych alarmow, a redaktor i tak
musial klikac "zatwierdz".
"""

from app.answer.build import normalize, quote_is_in_chunk

AKAPIT = "Nasiona najszybciej kiełkują w temperaturze 22–28°C, przy stałej wilgotności podłoża."


def test_doslowny_cytat_przechodzi():
    assert quote_is_in_chunk("Nasiona najszybciej kiełkują w temperaturze 22–28°C", AKAPIT)


def test_rozny_mysnik_przechodzi():
    """PDF lamie wiersze gdzie popadnie, a model przepisuje z pamieci wzrokowej.
    Polpauza kontra dywiz to nie jest falszerstwo cytatu."""
    assert quote_is_in_chunk("w temperaturze 22-28°C", AKAPIT)


def test_inne_biale_znaki_przechodza():
    assert quote_is_in_chunk("Nasiona   najszybciej\nkiełkują", AKAPIT)


def test_zmieniona_liczba_nie_przechodzi():
    """Najwazniejszy przypadek: model podmienia wartosc i probuje ja podeprzec
    cytatem, ktorego w zrodle nie ma."""
    assert not quote_is_in_chunk("w temperaturze 30-35°C", AKAPIT)


def test_dopisane_slowo_nie_przechodzi():
    assert not quote_is_in_chunk("Nasiona zawsze najszybciej kiełkują", AKAPIT)


def test_cytat_z_innego_akapitu_nie_przechodzi():
    assert not quote_is_in_chunk("Rozsadę sadzi się po 15 maja", AKAPIT)


def test_pusty_cytat_nie_przechodzi():
    """Pusty napis zawiera sie w kazdym tekscie - bez tego testu model moglby
    "potwierdzic" dowolne zdanie, nie podajac nic."""
    assert not quote_is_in_chunk("", AKAPIT)


def test_normalizacja_nie_zmienia_tresci():
    assert normalize("Tekst  z   odstępami") == "tekst z odstępami"

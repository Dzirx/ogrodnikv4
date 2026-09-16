"""Strony, na których tekst siedzi w obrazie.

Klient przecina grzbiety książek i przepuszcza je przez skaner - mówił to
wprost na spotkaniu. Taka książka wchodziła jako "gotowa" z zerową liczbą
akapitów, bez słowa ostrzeżenia.
"""

from app.ingest.ocr import MIN_PEWNOSC, MIN_PEWNOSC_SLOWA, ma_tresc


def test_prog_rozdziela_obraz_od_tekstu():
    """Zmierzone na książkach klienta: fotografia krzewów 31%, zdjęcie owocu 45%,
    okładka ze zdjęciem i nazwą instytucji 70%, strona tytułowa 90,6%, stopka
    z adresem 92,6%. Próg musi leżeć między okładką a stroną tytułową."""
    assert MIN_PEWNOSC > 70, "okładka ze zdjęciem przechodziła przy 65"
    assert MIN_PEWNOSC < 90, "strona tytułowa dała 90,6% i ma przechodzić"


def test_szum_z_fotografii_nie_ma_tresci():
    """Zdjęcie krzewów wyprodukowało 168 "słów" z liści i cieni, ale to
    'Rd"', 'AKRZE', '„ZEE'. Sam licznik słów by nie wystarczył - dlatego
    liczy się i treść, i pewność odczytu."""
    assert not ma_tresc('Rd" AKRZE ZEE WBELNS AA ji PDPZ')
    assert not ma_tresc("")


def test_prawdziwy_akapit_ma_tresc():
    assert ma_tresc(
        "Po wysadzeniu rozsady do gruntu należy zadbać o odpowiednie warunki uprawy, "
        "w tym nawodnienie, wentylację i temperaturę otoczenia roślin."
    )


def test_prog_slowa_nizszy_niz_prog_strony():
    """Strona czytelna jako całość może mieć w środku śmieci - na okładce
    nazwa instytucji wyszła poprawnie, a szum wokół niej nie."""
    assert MIN_PEWNOSC_SLOWA < MIN_PEWNOSC

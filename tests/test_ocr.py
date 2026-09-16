"""Strony, na których tekst siedzi w obrazie.

Klient przecina grzbiety książek i przepuszcza je przez skaner - mówił to
wprost na spotkaniu. Taka książka wchodziła jako "gotowa" z zerową liczbą
akapitów, bez słowa ostrzeżenia.
"""

from app.ingest.ocr import MIN_PEWNOSC, ma_tresc


def test_odczyt_z_fotografii_nie_przechodzi_progu_pewnosci():
    """Zmierzone na książkach klienta: zdjęcie krzewów w tunelu dało 31%,
    zdjęcie pękniętego owocu 45%. Tesseract sam mówi, że nie wie, co czyta."""
    assert MIN_PEWNOSC > 45, "próg musi odciąć szum z fotografii"
    assert MIN_PEWNOSC < 90, "prawdziwy tekst nie zawsze wychodzi idealnie"


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

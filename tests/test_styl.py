"""Kontrola języka - reguły wprost z uwag klienta.

Czyta to człowiek starszej daty, który natychmiast wyłapuje zdania urzędowe.
"""

import pytest

from app.answer.styl import MAX_WYRAZOW, policz_wyrazy, sprawdz


@pytest.mark.parametrize(
    "zdanie,czego_dotyczy",
    [
        ("Zalecane podłoże do siewu pomidorów ma pH 6,0–6,5.", "zalecane"),
        ("W tunelach należy monitorować temperaturę.", "należy"),
        ("Zaleca się stosowanie podłoża lekko kwaśnego.", "zaleca się"),
        ("Produkcję rozsady rozpoczyna się w marcu.", "produkcja rozsady"),
    ],
)
def test_wylapuje_urzedowe_zwroty(zdanie, czego_dotyczy):
    assert any(czego_dotyczy in u for u in sprawdz(zdanie))


def test_wylapuje_za_dlugie_zdanie():
    dlugie = (
        "Taki termin pozwala na posadzenie rozsady do gruntu w drugiej połowie maja, "
        "co jest optymalne dla rozwoju roślin w warunkach zewnętrznych ogrodu."
    )
    assert any("wyrazów" in u for u in sprawdz(dlugie))


def test_wylapuje_bledny_przyimek():
    """Zdanie wskazane przez klienta jako niepoprawne po polsku."""
    uwagi = sprawdz("Dla uprawy gruntowej pomidorów przygotuj stanowisko osłonięte.")
    assert any("W uprawie" in u for u in uwagi)


def test_wylapuje_doklejke_bez_tresci():
    uwagi = sprawdz("Pojemniki ulegają biodegradacji, co jest korzystne dla środowiska.")
    assert any("doklejka" in u for u in uwagi)


@pytest.mark.parametrize(
    "zdanie",
    [
        "Rozsadę na grunt wysiewa się w drugiej połowie marca.",
        "Pomidor lubi glebę o odczynie około 6,0.",
        "Do siewu weź podłoże o pH 6,0–6,5.",
        "W tunelu pilnuj, żeby temperatura nie przekraczała 30°C.",
    ],
)
def test_naturalne_zdania_przechodza(zdanie):
    assert sprawdz(zdanie) == []


def test_liczy_wyrazy_bez_interpunkcji():
    assert policz_wyrazy("Pomidor lubi glebę o odczynie 6,0.") == 6


@pytest.mark.parametrize(
    "zdanie,czego_dotyczy",
    [
        ("Pomidor preferuje podłoże żyzne i przepuszczalne.", "preferuje"),
        ("W przypadku upraw pod osłonami wietrz tunel.", "w przypadku"),
        ("Odmiana charakteryzuje się wysoką odpornością.", "charakteryzuje się"),
    ],
)
def test_wylapuje_jezyk_opracowan_fachowych(zdanie, czego_dotyczy):
    """Ogrodnik powie "lubi", nie "preferuje" - klient wyłapuje takie słowa."""
    assert any(czego_dotyczy in u for u in sprawdz(zdanie))


def test_wylapuje_powinno():
    """"Podłoże powinno być żyzne, a jego pH powinno wynosić..." - zdanie,
    które przeszło pierwszą wersję bramki."""
    uwagi = sprawdz("Podłoże dla pomidorów powinno być żyzne i przepuszczalne.")
    assert any("powinien" in u for u in uwagi)


def test_wylapuje_powtorzony_poczatek_zdan():
    """"Jeśli... Jeśli..." to wyliczanka faktów, nie wypowiedź. Model dostaje
    fakty jeden po drugim i bez tej kontroli opakowuje każdy w osobne zdanie
    warunkowe."""
    from app.answer.styl import sprawdz_odpowiedz

    zdania = [
        "Jeśli chcesz uprawiać pomidory w gruncie, siej w drugiej połowie marca.",
        "Jeśli planujesz uprawę pod osłonami, wysiej na początku marca.",
    ]
    uwagi = sprawdz_odpowiedz(zdania)

    assert 1 in uwagi
    assert any("tak samo" in u for u in uwagi[1])


def test_rozne_poczatki_zdan_przechodza():
    from app.answer.styl import sprawdz_odpowiedz

    zdania = [
        "Na grunt siej w drugiej połowie marca.",
        "Pod osłony wcześniej, bo już na początku marca.",
    ]
    assert sprawdz_odpowiedz(zdania) == {}

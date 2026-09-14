"""Dobór słów kluczowych do wyszukiwania po tekście.

Powód powstania: na pytanie "w jakim pH najlepiej sadzić pomidory" samo
wyszukiwanie wektorowe nie znalazło akapitu z "odczyn pH 6,0–6,5" — zwróciło
temperaturę, podlewanie i nawożenie. Model dostał tylko słabe akapity i ułożył
z nich odpowiedź, która nie odpowiadała na pytanie.
"""

from app.search.index import _slowa_kluczowe, _polacz, _wzorzec_calego_slowa


def test_odsiewa_slowa_nic_nie_wnoszace():
    """Szukanie po "w", "jakim" czy "najlepiej" zwróciłoby pół książki."""
    assert _slowa_kluczowe("w jakim pH najlepiej sadzić pomidory?") == ["ph", "sadzić", "pomidory"]


def test_zachowuje_krotki_termin_fachowy():
    """"pH" ma dwa znaki i właśnie ono niesie tu całą treść pytania."""
    assert "ph" in _slowa_kluczowe("jakie pH?")


def test_wzorzec_dopasowuje_cale_slowo():
    """Bez granic słowa "ph" trafiało w "Phytophthora" i akapit o zarazie
    ziemniaczanej wypychał z wyników ten o odczynie podłoża."""
    wzorzec = _wzorzec_calego_slowa("ph")
    assert wzorzec.startswith("\\m") and wzorzec.endswith("\\M")


def test_laczenie_premiuje_akapit_z_obu_list():
    wektorowe = [10, 20, 30]
    doslowne = [30, 40]
    wynik = _polacz(wektorowe, doslowne, limit=4)
    assert wynik[0] == 30  # jedyny obecny w obu


def test_laczenie_zachowuje_trafienia_z_jednej_listy():
    """Akapit znaleziony tylko po słowach nadal ma szansę - inaczej wróciłby
    problem, od którego się zaczęło."""
    assert 99 in _polacz([1, 2], [99], limit=5)


def test_puste_pytanie_nie_wywraca_wyszukiwania():
    assert _slowa_kluczowe("") == []
    assert _polacz([], [], limit=5) == []

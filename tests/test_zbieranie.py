"""Każda książka oddaje tyle samo, a o tym, co wejdzie do odpowiedzi, decyduje
osobny krok.

Pierwsza wersja robiła jeden wspólny ranking akapitów i wyrównywała go potem.
Działało przy dwóch książkach, rozsypywało się przy dwunastu: na dwanaście
miejsc wypadał jeden akapit na książkę, a część książek nie dostawała nic.
Liczba zaznaczonych książek nie może zmieniać zasad.
"""

from app.answer.build import przytnij_fakty
from app.db.base import SessionLocal
from app.db.models import Source
from app.search.index import NA_KSIAZKE, szukaj_w_kazdej_ksiazce


class _Akapit:
    def __init__(self, chunk_id, source_id):
        self.id = chunk_id
        self.source_id = source_id


def _fakty(ile, source_id=1, od=0):
    return [
        {"tresc": f"fakt {i}", "warunek": "", "chunk_id": i + od, "quote": "x"}
        for i in range(ile)
    ]


def _by_id(fakty, source_id):
    return {f["chunk_id"]: _Akapit(f["chunk_id"], source_id) for f in fakty}


def test_male_zbiory_ida_w_calosci():
    fakty = _fakty(5)

    assert przytnij_fakty(fakty, _by_id(fakty, 1), 12) == fakty


def test_przyciecie_nie_wycina_calej_ksiazki():
    """Gdyby brać po kolei, książka wypisana jako druga wypadłaby w całości."""
    pierwsza = _fakty(10, od=0)
    druga = _fakty(10, od=100)
    by_id = {**_by_id(pierwsza, 1), **_by_id(druga, 2)}

    wynik = przytnij_fakty(pierwsza + druga, by_id, 6)

    assert len(wynik) == 6
    z_pierwszej = [f for f in wynik if f["chunk_id"] < 100]
    assert len(z_pierwszej) == 3, "po równo z każdej książki"


def test_kazda_gotowa_ksiazka_dostaje_wlasne_miejsce():
    """Sedno zmiany: książka nie konkuruje z innymi o miejsce we wspólnym
    rankingu, tylko jest przeszukiwana na własnych prawach."""
    db = SessionLocal()
    gotowe = [s.id for s in db.query(Source).filter_by(status="ready").all()]
    db.close()
    if len(gotowe) < 2:
        return  # środowisko bez wgranych książek - nie ma czego sprawdzać

    wynik = szukaj_w_kazdej_ksiazce("w jakim pH sadzić pomidory?", gotowe)

    assert set(wynik) <= set(gotowe)
    assert len(wynik) >= 2, "każda książka z trafieniem ma własny wpis"
    for source_id, akapity in wynik.items():
        assert 0 < len(akapity) <= NA_KSIAZKE
        assert len(set(akapity)) == len(akapity)


def test_zawezenie_do_jednej_ksiazki_nie_wpuszcza_innych():
    db = SessionLocal()
    gotowe = [s.id for s in db.query(Source).filter_by(status="ready").all()]
    db.close()
    if not gotowe:
        return

    wynik = szukaj_w_kazdej_ksiazce("w jakim pH sadzić pomidory?", [gotowe[0]])

    assert set(wynik) <= {gotowe[0]}

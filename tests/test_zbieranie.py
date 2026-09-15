"""Każda książka oddaje tyle samo, a o tym, co wejdzie do odpowiedzi, decyduje
osobny krok.

Pierwsza wersja robiła jeden wspólny ranking akapitów i wyrównywała go potem.
Działało przy dwóch książkach, rozsypywało się przy dwunastu: na dwanaście
miejsc wypadał jeden akapit na książkę, a część książek nie dostawała nic.
Liczba zaznaczonych książek nie może zmieniać zasad.
"""

import app.answer.build as build
from app.answer.build import MAX_FAKTOW, wybierz_fakty
from app.db.base import SessionLocal
from app.db.models import Source
from app.search.index import NA_KSIAZKE, szukaj_w_kazdej_ksiazce


def _fakty(ile):
    return [{"tresc": f"fakt {i}", "warunek": "", "chunk_id": i, "quote": "x"} for i in range(ile)]


def test_malo_faktow_idzie_bez_pytania_modelu(monkeypatch):
    """Sędzia kosztuje wywołanie modelu - przy kilku faktach nie ma czego ważyć."""
    def nie_wolno(*_a, **_k):
        raise AssertionError("model nie powinien być wołany")

    monkeypatch.setattr(build._openai.chat.completions, "create", nie_wolno)
    fakty = _fakty(MAX_FAKTOW)

    assert wybierz_fakty("pytanie", fakty, {}, {}) == fakty


def test_gdy_sedzia_milczy_bierzemy_poczatek_listy(monkeypatch):
    """Gorsza odpowiedź jest lepsza niż brak odpowiedzi."""
    def zepsuty(*_a, **_k):
        raise RuntimeError("model niedostępny")

    monkeypatch.setattr(build._openai.chat.completions, "create", zepsuty)
    fakty = _fakty(MAX_FAKTOW + 10)

    wynik = wybierz_fakty("pytanie", fakty, {}, {})

    assert len(wynik) == MAX_FAKTOW
    assert wynik == fakty[:MAX_FAKTOW]


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

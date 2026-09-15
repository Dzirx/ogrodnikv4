"""Bramki, przez które para faktów musi przejść, zanim stanie się pytaniem
do człowieka.

Fałszywy spór kosztuje więcej niż przeoczony: przeoczony wróci przy kolejnym
pytaniu, fałszywy każe rozstrzygać coś, co sporem nie jest. Po kilku takich
nikt nie zajrzy do tej zakładki - a to jedyne miejsce, w którym program w ogóle
o coś pyta.
"""

import pytest

import app.answer.konflikty as K
from app.answer.konflikty import _zbuduj, odcisk, ustalenia_dla, warunek, zachodza_na_siebie
from app.db.base import SessionLocal
from app.db.models import Chunk, Conflict, ConflictOption, Page, Source


def test_warunek_bez_tresci_sprowadza_sie_do_pustego():
    """Model pisze brak warunku na kilka sposobów. Gdyby "brak" i pusty napis
    znaczyły co innego, spór przepadłby na bramce warunku."""
    assert warunek("brak") == warunek("") == warunek("nie podano") == ""
    assert warunek("Pod osłonami") == warunek("pod osłonami!") == "pod osłonami"


def test_zakresy_z_czescia_wspolna_nie_sa_sporem():
    """pH 5,5-6,5 i 6,0-7,0 nie wymagają niczyjej decyzji - każda wartość
    z części wspólnej spełnia oba zalecenia."""
    assert zachodza_na_siebie("5,5-6,5", "6,0-7,0")
    assert zachodza_na_siebie("22–28°C", "od 20 do 25°C")


def test_zakresy_rozlaczne_sa_sporem():
    assert not zachodza_na_siebie("5,5-6,5", "7,0-7,5")
    assert not zachodza_na_siebie("15 maja", "20 maja")


def test_wartosc_nieliczbowa_nie_przechodzi_przez_te_bramke():
    """Bez liczb nie ma czego porównać - decyduje model, nie ta reguła."""
    assert not zachodza_na_siebie("w drugiej połowie maja", "po przymrozkach")


def test_odcisk_nie_zalezy_od_kolejnosci_wartosci():
    """Ten sam spór zgłoszony w odwrotnej kolejności to nadal ten sam spór."""
    assert odcisk("odczyn gleby dla pomidora", ["5,5-6,5", "7,0"]) == odcisk(
        "odczyn gleby dla pomidora", ["7,0", "5,5-6,5"]
    )


AKAPIT_A = "Pomidory najlepiej rosną w glebie o odczynie 5,5-6,5, lekko kwaśnej i przepuszczalnej."
AKAPIT_B = "Odczyn gleby pod pomidory powinien wynosić 7,0-7,5, czyli lekko zasadowy."


@pytest.fixture
def dwie_ksiazki():
    """Dwie książki, po jednym akapicie każda - najmniejszy układ, w którym
    spór między źródłami w ogóle może powstać."""
    db = SessionLocal()
    zrodla, chunks = [], []
    for numer, tekst in enumerate((AKAPIT_A, AKAPIT_B), start=1):
        source = Source(title=f"pytest-konflikt {numer}", kind="pdf", object_key=f"pytest/{numer}", status="ready")
        db.add(source)
        db.flush()
        page = Page(source_id=source.id, number=1)
        db.add(page)
        db.flush()
        chunk = Chunk(source_id=source.id, page_id=page.id, seq=0, text=tekst)
        db.add(chunk)
        db.flush()
        zrodla.append(source)
        chunks.append(chunk)
    db.commit()

    yield db, chunks

    db.rollback()
    utworzone = db.query(Conflict).filter(Conflict.subject.like("pytest-%")).all()
    for k in utworzone:
        db.query(ConflictOption).filter_by(conflict_id=k.id).delete()
        db.delete(k)
    for chunk in chunks:
        db.query(ConflictOption).filter_by(chunk_id=chunk.id).delete()
        db.delete(chunk)
    db.commit()
    for source in zrodla:
        db.query(Page).filter_by(source_id=source.id).delete()
        db.delete(source)
    db.commit()
    db.close()


@pytest.fixture(autouse=True)
def bez_drugiej_oceny(monkeypatch):
    """Druga ocena to wywołanie modelu - w testach bramek sprawdzamy reguły,
    nie jego zdanie. Domyślnie przepuszcza; jeden test podmienia ją na odwrót."""
    monkeypatch.setattr(K, "naprawde_sprzeczne", lambda a, b: True)


def _fakt(chunk, tresc, cytat, war=""):
    return {"tresc": tresc, "warunek": war, "chunk_id": chunk.id, "quote": cytat}


def _spor(wartosc_a="5,5-6,5", wartosc_b="7,0-7,5", temat="pytest-odczyn gleby dla pomidora", war=""):
    return {"temat": temat, "warunek": war, "a": {"nr": 0, "wartosc": wartosc_a}, "b": {"nr": 1, "wartosc": wartosc_b}}


def test_dwie_ksiazki_o_tej_samej_rzeczy_daja_konflikt(dwie_ksiazki):
    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[1], "odczyn 7,0-7,5", "powinien wynosić 7,0-7,5"),
    ]

    konflikt = _zbuduj(db, _spor(), fakty, {c.id: c for c in chunks})

    assert konflikt is not None
    assert [o.value for o in konflikt.options] == ["5,5-6,5", "7,0-7,5"]


def test_rozne_warunki_to_nie_spor(dwie_ksiazki):
    """Najważniejsza bramka. "5,5-6,5 pod osłonami" i "7,0-7,5 w gruncie" to
    dwie różne sytuacje, nie sprzeczność."""
    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5", war="pod osłonami"),
        _fakt(chunks[1], "odczyn 7,0-7,5", "powinien wynosić 7,0-7,5", war="w gruncie"),
    ]

    assert _zbuduj(db, _spor(), fakty, {c.id: c for c in chunks}) is None


def test_ta_sama_ksiazka_nie_spiera_sie_sama_ze_soba(dwie_ksiazki):
    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[0], "odczyn 7,0-7,5", "lekko kwaśnej i przepuszczalnej"),
    ]

    assert _zbuduj(db, _spor(), fakty, {c.id: c for c in chunks}) is None


def test_zachodzace_zakresy_nie_daja_konfliktu(dwie_ksiazki):
    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[1], "odczyn 6,0-7,5", "powinien wynosić 7,0-7,5"),
    ]

    assert _zbuduj(db, _spor(wartosc_b="6,0-7,5"), fakty, {c.id: c for c in chunks}) is None


def test_cytat_ktorego_nie_ma_w_akapicie_zamyka_sprawe(dwie_ksiazki):
    """Ta sama bramka co przy odpowiedziach: model mógł wymyślić wartość
    i podeprzeć ją cytatem, którego w książce nie ma."""
    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[1], "odczyn 7,0-7,5", "powinien wynosić 8,0-8,5"),
    ]

    assert _zbuduj(db, _spor(), fakty, {c.id: c for c in chunks}) is None


def test_ten_sam_spor_nie_wraca_przy_kolejnym_pytaniu(dwie_ksiazki):
    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[1], "odczyn 7,0-7,5", "powinien wynosić 7,0-7,5"),
    ]
    by_id = {c.id: c for c in chunks}
    assert _zbuduj(db, _spor(), fakty, by_id) is not None
    db.commit()

    assert _zbuduj(db, _spor(), fakty, by_id) is None


def test_ta_sama_wartosc_innymi_slowami_to_nie_spor(dwie_ksiazki):
    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[1], "odczyn 5,5-6,5", "powinien wynosić 7,0-7,5"),
    ]

    assert _zbuduj(db, _spor(wartosc_b="5,5–6,5"), fakty, {c.id: c for c in chunks}) is None


def test_druga_ocena_moze_obalic_spor(dwie_ksiazki, monkeypatch):
    """Pierwsza ocena szuka sporów i znajduje ich za dużo - uznała
    "po minięciu przymrozków" i "gdy małe prawdopodobieństwo przymrozków,
    gleba 12-13 stopni" za spór, choć drugie doprecyzowuje pierwsze. Druga
    ocena dostaje same cytaty i ma je pogodzić."""
    db, chunks = dwie_ksiazki
    monkeypatch.setattr(K, "naprawde_sprzeczne", lambda a, b: False)
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[1], "odczyn 7,0-7,5", "powinien wynosić 7,0-7,5"),
    ]

    assert _zbuduj(db, _spor(), fakty, {c.id: c for c in chunks}) is None


def test_rozstrzygniecie_wraca_przy_akapicie_ktorego_dotyczylo(dwie_ksiazki):
    """Bez tego rozstrzygnięcie sporu nie zmieniałoby niczego w odpowiedziach,
    a zakładka obiecuje, że program zapamięta i będzie stosował."""
    from datetime import datetime

    db, chunks = dwie_ksiazki
    fakty = [
        _fakt(chunks[0], "odczyn 5,5-6,5", "o odczynie 5,5-6,5"),
        _fakt(chunks[1], "odczyn 7,0-7,5", "powinien wynosić 7,0-7,5"),
    ]
    konflikt = _zbuduj(db, _spor(), fakty, {c.id: c for c in chunks})
    db.commit()

    assert ustalenia_dla(db, [chunks[0].id]) == [], "spór otwarty nie jest jeszcze ustaleniem"

    konflikt.status = "resolved"
    konflikt.resolved_value = "5,7"
    konflikt.resolved_origin = "editorial"
    konflikt.resolved_at = datetime.utcnow()
    db.commit()

    ustalenia = ustalenia_dla(db, [chunks[0].id])
    assert len(ustalenia) == 1
    assert ustalenia[0]["wartosc"] == "5,7"
    assert ustalenia[0]["wlasne"] is True
    assert ustalenia_dla(db, []) == []

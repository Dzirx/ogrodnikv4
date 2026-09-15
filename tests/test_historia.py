"""Pasek wątków po lewej rośnie bez końca, jeśli go nie przyciąć.

Redaktor zadaje dziesiątki pytań, a szuka zawsze wśród ostatnich. Pokazujemy
dwadzieścia i link do starszych - bez skryptu, zwykłym adresem."""

from app.api.routes import POKAZ_ROZMOW, _historia
from app.db.base import SessionLocal
from app.db.models import Conversation


def _posprzataj(db, rozmowy):
    for r in rozmowy:
        db.delete(r)
    db.commit()


def test_pokazuje_najnowsze_i_liczy_starsze():
    db = SessionLocal()
    dodane = [Conversation(title=f"pytest-historia {i}") for i in range(POKAZ_ROZMOW + 5)]
    db.add_all(dodane)
    db.commit()
    try:
        wynik = _historia(db, POKAZ_ROZMOW)

        assert len(wynik["rozmowy"]) == POKAZ_ROZMOW
        assert wynik["rozmowy"][0].id > wynik["rozmowy"][-1].id
        assert wynik["starsze"] >= 5
        assert wynik["nastepne"] == POKAZ_ROZMOW * 2
    finally:
        _posprzataj(db, dodane)
        db.close()


def test_otwarty_watek_zostaje_widoczny_choc_jest_stary():
    """Inaczej klikasz w wątek i znika z listy, w której go kliknąłeś."""
    db = SessionLocal()
    dodane = [Conversation(title=f"pytest-historia-stara {i}") for i in range(POKAZ_ROZMOW + 5)]
    db.add_all(dodane)
    db.commit()
    najstarsza = dodane[0]
    try:
        wynik = _historia(db, POKAZ_ROZMOW, najstarsza)

        assert najstarsza.id in [r.id for r in wynik["rozmowy"]]
    finally:
        _posprzataj(db, dodane)
        db.close()


def test_prog_nie_da_sie_zejsc_ponizej_dwudziestu():
    """Adres z ?historia=1 nie ma prawa zostawić paska z jednym wątkiem."""
    db = SessionLocal()
    try:
        assert len(_historia(db, 1)["rozmowy"]) <= POKAZ_ROZMOW
        assert _historia(db, 1)["nastepne"] == POKAZ_ROZMOW * 2
    finally:
        db.close()

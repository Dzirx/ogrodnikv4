"""Listy, które rosną bez końca: wątki po lewej i źródła.

Redaktor zadaje dziesiątki pytań, a szuka zawsze wśród ostatnich. Pokazujemy
dwadzieścia i link do starszych - bez skryptu, zwykłym adresem."""

from app.api.routes import POKAZ_ROZMOW, POKAZ_ZRODEL, _historia, zrodla
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


class _Zadanie:
    """Request wystarczający dla tych tras - szablon czyta z niego tylko
    parametry zapytania."""

    query_params: dict = {}


def test_zrodla_bez_filtra_pokazuja_wszystko():
    db = SessionLocal()
    try:
        ctx = zrodla(_Zadanie(), db=db).context

        assert ctx["pasujacych"] == ctx["wszystkich"]
        assert len(ctx["zrodla"]) == min(ctx["wszystkich"], POKAZ_ZRODEL)
        assert ctx["starsze"] == max(ctx["wszystkich"] - POKAZ_ZRODEL, 0)
    finally:
        db.close()


def test_szukanie_zawezaja_liste_ale_licznik_calosci_zostaje():
    """Nagłówek ma mówić "1 z 60", żeby było widać, że reszta nie zniknęła."""
    db = SessionLocal()
    try:
        wszystkich = zrodla(_Zadanie(), db=db).context["wszystkich"]
        ctx = zrodla(_Zadanie(), szukaj="na pewno nie ma takiego tytułu", db=db).context

        assert ctx["zrodla"] == []
        assert ctx["pasujacych"] == 0
        assert ctx["wszystkich"] == wszystkich
    finally:
        db.close()


def test_prog_zrodel_nie_da_sie_zejsc_ponizej_domyslnego():
    db = SessionLocal()
    try:
        assert zrodla(_Zadanie(), ile=1, db=db).context["nastepne"] == POKAZ_ZRODEL * 2
    finally:
        db.close()


def test_ksiazka_zaznaczona_dwa_razy_nie_wywraca_pytania():
    """Książka z dwiema etykietami stoi w wyborze źródeł w dwóch grupach.
    Zaznaczenie obu wysyłało jej numer dwa razy, baza odrzucała duplikat klucza
    i całe pytanie kończyło się błędem serwera."""
    from app.api.routes import bez_powtorzen

    assert bez_powtorzen([1, 2, 2]) == [1, 2]
    assert bez_powtorzen([2, 1, 2, 1]) == [2, 1], "kolejność zaznaczenia zostaje"
    assert bez_powtorzen([]) == []

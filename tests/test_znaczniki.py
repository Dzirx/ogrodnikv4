"""Przypisy do źródeł w poprawionym tekście.

Po ręcznej edycji nie da się przypisać źródeł do zdań automatycznie — tekst
jest już redaktora. Dlatego edytuje go razem ze znacznikami [1], [2] i sam
decyduje, gdzie mają stać. Przypisy na marginesie to nie to samo, co przypis
przy zdaniu.
"""

from app.api.routes import rozbij_znaczniki, tekst_ze_znacznikami

ZRODLA = [
    {"marker": 1, "chunk_id": 10, "source_title": "Sułek", "page": 30},
    {"marker": 2, "chunk_id": 20, "source_title": "PODR", "page": 55},
]


def test_sklada_tekst_ze_znacznikami_do_edycji():
    odpowiedz = {
        "sentences": [
            {"text": "Lej pod krzew.", "source": {"marker": 2}},
            {"text": "Najlepsza jest deszczówka.", "source": {"marker": 1}},
        ]
    }
    assert tekst_ze_znacznikami(odpowiedz) == "Lej pod krzew. [2] Najlepsza jest deszczówka. [1]"


def test_zdanie_bez_zrodla_nie_dostaje_znacznika():
    odpowiedz = {"sentences": [{"text": "Zdanie bez źródła.", "source": None}]}
    assert tekst_ze_znacznikami(odpowiedz) == "Zdanie bez źródła."


def test_rozbija_tekst_na_fragmenty_i_odnosniki():
    czesci = rozbij_znaczniki("Lej pod krzew. [2] Potem podlej. [1]", ZRODLA)

    assert czesci[0]["tekst"] == "Lej pod krzew. "
    assert czesci[1]["znacznik"] == 2
    assert czesci[1]["zrodlo"]["chunk_id"] == 20
    assert czesci[3]["znacznik"] == 1


def test_nieznany_numer_zostaje_tekstem():
    """Redaktor mógł wpisać [9] z palca - nie udajemy, że to odnośnik."""
    czesci = rozbij_znaczniki("Coś tam [9] dalej.", ZRODLA)

    assert all("znacznik" not in c for c in czesci)
    assert "".join(c["tekst"] for c in czesci) == "Coś tam [9] dalej."


def test_tekst_bez_znacznikow_zostaje_caly():
    czesci = rozbij_znaczniki("Zwykły tekst bez przypisów.", ZRODLA)
    assert czesci == [{"tekst": "Zwykły tekst bez przypisów."}]

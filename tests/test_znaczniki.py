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
    """Kawałek to część zdania, więc znacznik stoi tuż za nim - bez spacji,
    tak jak przypis w książce."""
    odpowiedz = {
        "sentences": [
            {"text": "Podlewaj 2-3 razy w tygodniu", "sources": [{"marker": 1}]},
            {"text": " — zawsze pod krzew.", "sources": [{"marker": 2}]},
        ]
    }
    assert tekst_ze_znacznikami(odpowiedz) == "Podlewaj 2-3 razy w tygodniu[1] — zawsze pod krzew.[2]"


def test_kawalek_moze_miec_kilka_przypisow():
    """Jedno zdanie potrafi stać na dwóch akapitach z różnych książek."""
    odpowiedz = {"sentences": [{"text": "Lej pod krzew.", "sources": [{"marker": 1}, {"marker": 2}]}]}
    assert tekst_ze_znacznikami(odpowiedz) == "Lej pod krzew.[1][2]"


def test_brakujaca_spacja_miedzy_kawalkami_jest_dokladana():
    """Model ma zaczynać kawałek od spacji, gdy stoi w środku zdania. Gdy
    zapomni, sklejone słowa wyglądają na błąd programu."""
    odpowiedz = {
        "sentences": [
            {"text": "Siej w marcu.", "sources": []},
            {"text": "Pod osłony wcześniej.", "sources": []},
        ]
    }
    assert tekst_ze_znacznikami(odpowiedz) == "Siej w marcu. Pod osłony wcześniej."


def test_spacja_na_koncu_kawalka_nie_odkleja_przypisu():
    """Model często zostawia spację na końcu. Znacznik musi stać przy słowie,
    nie przy następnym zdaniu."""
    odpowiedz = {
        "sentences": [
            {"text": "Podlewaj co drugi dzień. ", "sources": [{"marker": 1}]},
            {"text": "W upały częściej.", "sources": [{"marker": 2}]},
        ]
    }
    assert tekst_ze_znacznikami(odpowiedz) == "Podlewaj co drugi dzień.[1] W upały częściej.[2]"


def test_przed_przecinkiem_spacji_nie_dokladamy():
    odpowiedz = {"sentences": [{"text": "Siej w marcu", "sources": []}, {"text": ", pod osłony wcześniej.", "sources": []}]}
    assert tekst_ze_znacznikami(odpowiedz) == "Siej w marcu, pod osłony wcześniej."


def test_kawalek_bez_zrodla_nie_dostaje_znacznika():
    odpowiedz = {"sentences": [{"text": "Zdanie bez źródła.", "sources": []}]}
    assert tekst_ze_znacznikami(odpowiedz) == "Zdanie bez źródła."


def test_starsza_rozmowa_z_pojedynczym_zrodlem_nadal_sie_sklada():
    """Rozmowy zapisane, zanim jednostką stał się kawałek zdania, mają w bazie
    pojedyncze "source" przy całym zdaniu. Muszą się nadal wyświetlać."""
    odpowiedz = {
        "sentences": [
            {"text": "Lej pod krzew.", "source": {"marker": 2}},
            {"text": "Najlepsza jest deszczówka.", "source": {"marker": 1}},
        ]
    }
    assert tekst_ze_znacznikami(odpowiedz) == "Lej pod krzew.[2] Najlepsza jest deszczówka.[1]"


def test_rozbija_tekst_na_fragmenty_i_odnosniki():
    czesci = rozbij_znaczniki("Lej pod krzew.[2] Potem podlej.[1]", ZRODLA)

    assert czesci[0]["tekst"] == "Lej pod krzew."
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

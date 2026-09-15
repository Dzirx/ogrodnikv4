"""Przypisy do źródeł w tekście odpowiedzi i w oknie edycji.

Odnośnik pokazujemy tylko tam, gdzie odcinek niesie twardą wartość - liczbę,
dawkę, odczyn. Zdanie ogólne ma swoje źródło zapisane w bazie, ale cyferki przy
nim nie rysujemy: "każde zdanie ma źródło" robiło z porady pracę naukową.

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
            {"text": " — pod krzew, nie na liście.", "sources": [{"marker": 2}]},
        ]
    }
    # Pierwszy odcinek ma liczbę; drugi kończy akapit, więc też dostaje odnośnik -
    # w dłuższym tekście jedna cyferka na sześć akapitów wyglądała na tekst
    # wzięty z powietrza.
    assert tekst_ze_znacznikami(odpowiedz) == "Podlewaj 2-3 razy w tygodniu[1] — pod krzew, nie na liście.[2]"


def test_kawalek_moze_miec_kilka_przypisow():
    """Jedno zdanie potrafi stać na dwóch akapitach z różnych książek."""
    odpowiedz = {"sentences": [{"text": "Lej 2 litry pod krzew.", "sources": [{"marker": 1}, {"marker": 2}]}]}
    assert tekst_ze_znacznikami(odpowiedz) == "Lej 2 litry pod krzew.[1][2]"


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
            {"text": "Podlewaj co 2 dni. ", "sources": [{"marker": 1}]},
            {"text": "W upały co 1 dzień.", "sources": [{"marker": 2}]},
        ]
    }
    assert tekst_ze_znacznikami(odpowiedz) == "Podlewaj co 2 dni.[1] W upały co 1 dzień.[2]"


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
            {"text": "Lej 2 litry pod krzew.", "source": {"marker": 2}},
            {"text": "Najlepsza jest deszczówka.", "source": {"marker": 1}},
        ]
    }
    # Drugie zdanie nie niesie liczby, ale kończy tekst - odnośnik zostaje.
    assert tekst_ze_znacznikami(odpowiedz) == "Lej 2 litry pod krzew.[2] Najlepsza jest deszczówka.[1]"


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


def _kawalek(tekst, marker=None, **reszta):
    zrodla = [{"marker": marker, "chunk_id": marker}] if marker else []
    return {"text": tekst, "verified": True, "sources": zrodla, **reszta}


def test_odnosnik_pokazuje_sie_raz_na_odcinek():
    """Model podaje źródło do każdego kawałka i tak ma zostać - na tym stoi
    weryfikacja. Ale osiem cyferek na sześć zdań robiło z odpowiedzi pracę
    naukową zamiast porady."""
    from app.api.routes import czesci_odpowiedzi

    odpowiedz = {
        "sentences": [
            _kawalek("Podlewaj 2-3 razy w tygodniu", 1),
            _kawalek(" — ", spoiwo=True),
            _kawalek("częściej w upały.", 1),
            _kawalek(" Woda ma mieć 18 stopni.", 2),
            _kawalek(" Lej pod krzew.", 2),
            _kawalek(" Rankiem albo wieczorem.", 3),
        ]
    }

    widoczne = [[z["marker"] for z in c["znaczniki"]] for c in czesci_odpowiedzi(odpowiedz)]

    # Odcinek 1 i 2 niosą liczbę, trzeci nie - stąd dwie cyferki zamiast sześciu.
    # Trzeci odcinek nie ma liczby, ale kończy tekst - dostaje odnośnik.
    assert widoczne == [[], [], [1], [], [2], [3]]


def test_spoiwo_nie_przerywa_odcinka():
    """Przecinek ani myślnik nie zmieniają tego, skąd pochodzi zdanie."""
    from app.api.routes import czesci_odpowiedzi

    odpowiedz = {"sentences": [_kawalek("Lej 2 litry", 1), _kawalek(", a ", spoiwo=True), _kawalek("w upały więcej.", 1)]}

    assert [[z["marker"] for z in c["znaczniki"]] for c in czesci_odpowiedzi(odpowiedz)] == [[], [], [1]]


def test_ustalenie_przerywa_odcinek():
    """Wartość rozstrzygnięta przez człowieka to inne źródło informacji niż
    książka - odnośnik do książki musi zdążyć stanąć przed nią."""
    from app.api.routes import czesci_odpowiedzi

    odpowiedz = {
        "sentences": [
            _kawalek("Pomidory lubią odczyn 5,5-6,5", 1),
            _kawalek(" albo 6,2.", ustalenie="odczyn gleby"),
            _kawalek(" Gleba ma mieć 3% próchnicy.", 1),
        ]
    }

    assert [[z["marker"] for z in c["znaczniki"]] for c in czesci_odpowiedzi(odpowiedz)] == [[1], [], [1]]


def test_okno_edycji_dostaje_te_same_odnosniki_co_ekran():
    """Inaczej po kliknięciu "popraw" tekst wyglądałby inaczej niż przed chwilą."""
    odpowiedz = {"sentences": [_kawalek("Lej 2 litry pod krzew", 1), _kawalek(" i nie mocz liści.", 1)]}

    assert tekst_ze_znacznikami(odpowiedz) == "Lej 2 litry pod krzew i nie mocz liści.[1]"


def test_odcinek_bez_liczby_zostaje_bez_cyferki():
    """Sedno zmiany: "Zrób podstawowe badanie gleby w OSCHR" ma swoje źródło
    w bazie, ale cyferka przy nim niczego nie wnosi - nie ma czego sprawdzać."""
    from app.api.routes import czesci_odpowiedzi

    odpowiedz = {
        "sentences": [
            _kawalek("Zrób podstawowe badanie gleby w OSCHR.", 4),
            _kawalek(" Kompost dodaj w ilości 3 kg na metr.", 5),
        ]
    }

    czesci = czesci_odpowiedzi(odpowiedz)

    assert czesci[0]["znaczniki"] == [], "odcinek bez liczby w środku akapitu"
    assert czesci[0]["zrodla"], "źródło zostaje w danych, znika tylko z ekranu"
    assert [z["marker"] for z in czesci[1]["znaczniki"]] == [5], "ma liczbę i kończy akapit"


def test_zrodla_pod_odpowiedzia_grupuja_strony_po_ksiazkach():
    """Skoro w tekście zostają tylko niektóre odnośniki, komplet musi być widać
    w jednym miejscu."""
    from app.api.routes import zrodla_podsumowanie

    odpowiedz = {
        "sources": [
            {"marker": 1, "chunk_id": 10, "source_title": "Sułek", "page": 35},
            {"marker": 2, "chunk_id": 11, "source_title": "Sułek", "page": 31},
            {"marker": 3, "chunk_id": 12, "source_title": "PODR", "page": 12},
        ]
    }

    assert zrodla_podsumowanie(odpowiedz) == [
        {"tytul": "Sułek", "strony": [31, 35], "chunk_id": 10},
        {"tytul": "PODR", "strony": [12], "chunk_id": 12},
    ]

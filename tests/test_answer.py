"""Weryfikacja cytatow - jedyna bramka, ktora trzyma kod.

Model pisze, kod sprawdza czy cytat naprawde jest w akapicie. Reguly
normalizacji pochodza wprost z bledow pierwszej wersji: tam cytat odrzucony
za jeden mysnik byl najczestsza przyczyna falszywych alarmow, a redaktor i tak
musial klikac "zatwierdz".
"""

from app.answer.cytaty import normalize, quote_is_in_chunk

AKAPIT = "Nasiona najszybciej kiełkują w temperaturze 22–28°C, przy stałej wilgotności podłoża."


def test_doslowny_cytat_przechodzi():
    assert quote_is_in_chunk("Nasiona najszybciej kiełkują w temperaturze 22–28°C", AKAPIT)


def test_rozny_mysnik_przechodzi():
    """PDF lamie wiersze gdzie popadnie, a model przepisuje z pamieci wzrokowej.
    Polpauza kontra dywiz to nie jest falszerstwo cytatu."""
    assert quote_is_in_chunk("w temperaturze 22-28°C", AKAPIT)


def test_inne_biale_znaki_przechodza():
    assert quote_is_in_chunk("Nasiona   najszybciej\nkiełkują", AKAPIT)


def test_zmieniona_liczba_nie_przechodzi():
    """Najwazniejszy przypadek: model podmienia wartosc i probuje ja podeprzec
    cytatem, ktorego w zrodle nie ma."""
    assert not quote_is_in_chunk("w temperaturze 30-35°C", AKAPIT)


def test_dopisane_slowo_nie_przechodzi():
    assert not quote_is_in_chunk("Nasiona zawsze najszybciej kiełkują", AKAPIT)


def test_cytat_z_innego_akapitu_nie_przechodzi():
    assert not quote_is_in_chunk("Rozsadę sadzi się po 15 maja", AKAPIT)


def test_pusty_cytat_nie_przechodzi():
    """Pusty napis zawiera sie w kazdym tekscie - bez tego testu model moglby
    "potwierdzic" dowolne zdanie, nie podajac nic."""
    assert not quote_is_in_chunk("", AKAPIT)


def test_normalizacja_nie_zmienia_tresci():
    assert normalize("Tekst  z   odstępami") == "tekst z odstępami"


def test_normalizacja_laczy_rozne_mysniki():
    """PDF używa półpauzy, model często przepisuje dywizem."""
    assert normalize("22–28") == normalize("22-28")


def test_gdy_model_zawiedzie_forme_widac_po_slowach(monkeypatch):
    """Gorsze wyszukiwanie jest lepsze niż brak odpowiedzi - a "napisz artykuł"
    nie może przepaść tylko dlatego, że wywołanie rozpoznające padło."""
    import app.answer.build as build

    class Zepsuty:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    raise RuntimeError("model niedostępny")

    monkeypatch.setattr(build, "_openai", Zepsuty)

    assert build.zrozum_pytanie([], "w jakim pH sadzić pomidory?") == {
        "pytanie": "w jakim pH sadzić pomidory?",
        "forma": "odpowiedz",
        "o_uprawie": True,
        "temat": "",
        "ile_slow": None,
    }

    zapasowe = build.zrozum_pytanie([], "napisz mi artykuł na 1000 słów o tunelach")
    assert zapasowe["forma"] == "material"
    assert zapasowe["ile_slow"] == 1000


def test_forma_skaluje_zakres_wyszukiwania():
    """Prośba o materiał musi dać więcej materiału, nie to samo co zawsze.

    Zakres rośnie teraz planem zagadnień, nie liczbą akapitów na książkę:
    każde zagadnienie to osobne wyszukiwanie w każdej książce."""
    from app.answer.build import FORMY

    assert FORMY["odpowiedz"]["faktow"] < FORMY["rozwiniecie"]["faktow"] < FORMY["material"]["faktow"]
    assert not FORMY["odpowiedz"]["planuje"], "na pytanie o odczyn gleby nie ma czego planować"
    assert not FORMY["post"]["planuje"]
    assert FORMY["material"]["planuje"]
    assert FORMY["rozwiniecie"]["planuje"]
    for forma in ("odpowiedz", "rozwiniecie", "material", "post", "lista"):
        assert FORMY[forma]["jak"], f"{forma} musi mieć własną instrukcję pisania"


def test_pytanie_spoza_dziedziny_konczy_sie_przed_wyszukiwaniem(monkeypatch):
    """Pytanie o pogodę przechodziło całą drogę i kosztowało kilkanaście wywołań,
    żeby na końcu usłyszeć to samo."""
    import app.answer.build as build

    monkeypatch.setattr(
        build, "zrozum_pytanie",
        lambda h, p: {"pytanie": p, "forma": "odpowiedz", "o_uprawie": False, "temat": ""},
    )
    monkeypatch.setattr(
        build, "zbierz_fakty_do_pytania",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie wolno szukać")),
    )

    wynik = build.answer_question("jaka jest pogoda w Zakopanem?")

    assert wynik["sentences"] == []
    assert "nie dotyczy uprawy" in wynik["note"]


def test_sklejone_kawalki_daja_jeden_akapit():
    """Jednostką tekstu jest kawałek zdania, nie zdanie. Sklejone muszą się
    czytać jak zwykła wypowiedź, także gdy model zapomni o spacji."""
    from app.answer.build import sklej

    czesci = [
        {"text": "Podlewaj 2-3 razy w tygodniu"},
        {"text": " — zawsze pod krzew."},
        {"text": "Najlepsza jest deszczówka"},
        {"text": ", nie woda z kranu."},
    ]

    assert sklej(czesci) == (
        "Podlewaj 2-3 razy w tygodniu — zawsze pod krzew. Najlepsza jest deszczówka, nie woda z kranu."
    )


def test_spoiwo_bez_przypisu_jest_dozwolone():
    """Kawałek bez przypisu ma prawo istnieć tylko jako spoiwo. Bez tej furtki
    każdy kawałek musiał być samodzielną porcją faktu, więc model ciął
    wyłącznie na granicy zdania i odpowiedź wyglądała jak wyliczanka."""
    from app.answer.build import jest_spoiwem

    assert jest_spoiwem(" — ")
    assert jest_spoiwem(", a ")
    assert jest_spoiwem(". Za to ")


def test_tresc_bez_przypisu_spoiwem_nie_jest():
    """Przez tę furtkę nie ma wejść nic, co cokolwiek twierdzi."""
    from app.answer.build import jest_spoiwem

    assert not jest_spoiwem(", a w upały częściej")
    assert not jest_spoiwem("zawsze pod krzew")
    assert not jest_spoiwem(" — 2-3 razy w tygodniu")


def test_cytat_przechodzi_mimo_wyrazu_zlamanego_bez_myslnika():
    """PDF łamie wyraz na granicy wiersza, czasem bez myślnika: "dokład\\nnie"
    zostaje jako "dokład nie". Model czyta to jako jedno słowo i ma rację."""
    akapit = "System kroplowania kieruje wodę dokład nie pod korzeń rośliny."

    assert quote_is_in_chunk("kieruje wodę dokładnie pod korzeń", akapit)


def test_zmieniona_liczba_nie_przechodzi_takze_bez_odstepow():
    """Rozluźnienie dotyczy odstępów, nie treści."""
    akapit = "Nasiona kiełkują w temperaturze 22-28°C przy stałej wilgotności."

    assert not quote_is_in_chunk("kiełkują w temperaturze 30-35°C", akapit)
    assert not quote_is_in_chunk("kiełkują w temperaturze 22-28°C zawsze", akapit)


def test_sklejone_zdania_w_kawalku_dostaja_spacje():
    """Literówka modelu w środku kawałka: "agrowłókniną.Nie ma potrzeby".
    Sklejanie kawałków tego nie łapie, bo to jeden kawałek."""
    from app.answer.build import _brakujaca_spacja

    assert _brakujaca_spacja("agrowłókniną.Nie ma potrzeby") == "agrowłókniną. Nie ma potrzeby"
    assert _brakujaca_spacja("pH 6,0.Gleba ma być żyzna") == "pH 6,0.Gleba ma być żyzna", (
        "po cyfrze nie ruszamy - to może być liczba dziesiętna albo numer"
    )
    assert _brakujaca_spacja("3.5 kg") == "3.5 kg"


def test_zdanie_przejsciowe_zostaje_bez_przypisu():
    """Sedno zmiany: tekst ma móc mieć przejścia i wprowadzenia. Dotąd kawałek
    bez faktu przechodził tylko jako przecinek albo spójnik, więc model pisał
    fakt za faktem."""
    from app.answer.kontrola import do_usuniecia

    przejscie = {"twierdzi": False, "wynika": True, "warunek": True, "co_nie_pasuje": ""}

    assert not do_usuniecia(przejscie)


def test_twierdzenie_bez_pokrycia_wypada():
    from app.answer.kontrola import do_usuniecia

    assert do_usuniecia({"twierdzi": True, "wynika": False, "warunek": True, "co_nie_pasuje": "dopisana przyczyna"})


def test_zgubiony_warunek_oznacza_zamiast_usuwac():
    """Fakt "pod osłonami podlewać częściej" zamieniony na "podlewaj częściej"
    wprowadza w błąd, ale usuwanie za to okazało się za ostre: w jednym
    przebiegu wyleciały cztery zdania, w tym poprawne, i tekst zaczynał się
    w połowie myśli. Błąd warunku jest częściej pomyłką oceniającego niż błędem
    tekstu, a kosztuje cały akapit."""
    from app.answer.kontrola import do_oznaczenia, do_usuniecia

    zgubiony = {"twierdzi": True, "wynika": True, "warunek": False, "co_nie_pasuje": "zgubione osłony"}

    assert not do_usuniecia(zgubiony)
    assert do_oznaczenia(zgubiony)


def test_zdania_skladane_z_kawalkow_po_znaku_konca():
    from app.answer.build import _na_zdania

    czesci = [
        {"text": "Podlewaj 2-3 razy w tygodniu", "fakty_nr": [0]},
        {"text": " — ", "fakty_nr": []},
        {"text": "w upały częściej.", "fakty_nr": [1]},
        {"text": " Przejdźmy do nawożenia.", "fakty_nr": []},
    ]
    fakty = [{"tresc": "podlewać 2-3 razy w tygodniu"}, {"tresc": "w upały częściej"}]

    zdania = _na_zdania(czesci, fakty)

    assert len(zdania) == 2
    assert zdania[0]["indeksy"] == [0, 1, 2]
    assert zdania[0]["fakty"] == ["podlewać 2-3 razy w tygodniu", "w upały częściej"]
    assert zdania[1]["fakty"] == []


def test_forma_po_slowach_rozpoznaje_wszystkie_rodzaje():
    from app.answer.build import forma_po_slowach

    assert forma_po_slowach("napisz artykuł o tunelach") == "material"
    assert forma_po_slowach("wrzuć posta na fb") == "post"
    assert forma_po_slowach("wypisz punktami czym nawozić") == "lista"
    assert forma_po_slowach("rozpisz to dokładniej") == "rozwiniecie"
    assert forma_po_slowach("w jakim pH sadzić pomidory?") == "odpowiedz"


def test_dlugosc_z_polecenia():
    from app.answer.build import zadana_dlugosc

    assert zadana_dlugosc("napisz na 1000 słów") == 1000
    assert zadana_dlugosc("artykuł około 500 slow") == 500
    assert zadana_dlugosc("jak podlewać pomidory?") is None


def test_naprawa_szwow_moze_tylko_skracac():
    """Cała gwarancja tego kroku: skoro naprawa tylko usuwa słowa, nie da się
    przy zszywaniu wprowadzić nowej treści."""
    from app.answer.kontrola import tylko_skrocone

    assert tylko_skrocone("Dlatego pomidory rosną lepiej.", "Pomidory rosną lepiej.")
    assert tylko_skrocone("Te dwa sposoby są skuteczne.", "sposoby są skuteczne")
    assert tylko_skrocone("cokolwiek", "")
    assert not tylko_skrocone("Pomidory rosną lepiej.", "Pomidory rosną lepiej i szybciej.")
    assert not tylko_skrocone("Pomidory rosną lepiej.", "Lepiej rosną pomidory."), "kolejność też się liczy"

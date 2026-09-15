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


def test_pierwsze_pytanie_nie_jest_przepisywane():
    """Bez historii nie ma czego uzupełniać - i nie ma po co płacić za
    wywołanie modelu."""
    from app.answer.build import przepisz_pytanie

    assert przepisz_pytanie([], "w jakim pH sadzić pomidory?") == "w jakim pH sadzić pomidory?"


def test_przepisanie_wraca_do_oryginalu_gdy_model_zawiedzie(monkeypatch):
    """Gorsze wyszukiwanie jest lepsze niż brak odpowiedzi."""
    import app.answer.build as build

    class Zepsuty:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    raise RuntimeError("model niedostępny")

    monkeypatch.setattr(build, "_openai", Zepsuty)
    historia = [("user", "wysiew pomidora"), ("assistant", "Wysiewa się w marcu.")]

    assert build.przepisz_pytanie(historia, "a w tunelu?") == "a w tunelu?"


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

from app.ingest.chunks import looks_like_noise, split_into_paragraphs


def test_dzieli_po_pustych_liniach():
    text = (
        "Pomidory gruntowe wymagają stanowiska osłoniętego od wiatru.\n\n"
        "Rozsadę wysiewa się w drugiej połowie marca, do gruntu po 15 maja."
    )
    assert len(split_into_paragraphs(text)) == 2


def test_skleja_przeniesienie_wyrazu():
    """W PDF-ie "wypeł-\\nnione" to jedno slowo. Bez sklejenia cytat modelu
    nigdy nie zgodzi sie ze zrodlem - w pierwszej wersji to byla najczestsza
    przyczyna falszywych odrzucen."""
    text = "Pomidory sadzi się w pierścienie wypeł-\nnione odkwaszonym torfem o odczynie zbliżonym do obojętnego."
    assert "wypełnione" in split_into_paragraphs(text)[0]


def test_odsiewa_spis_tresci():
    assert looks_like_noise("6.8. Odchwaszczanie . . . . . . . . . . . . . . . 65")


def test_odsiewa_numer_strony():
    assert looks_like_noise("  42  ")


def test_odsiewa_za_krotkie():
    assert looks_like_noise("Uprawa.")


def test_zachowuje_krotkie_ale_tresciwe_zdanie():
    """Prog dlugosci nie moze odsiewac faktow. To zdanie ma 51 znakow i jest
    dokladnie tym, po co ten system powstal."""
    assert not looks_like_noise("Nasiona kiełkują najszybciej w 22–28 stopniach.")


def test_zachowuje_tresc():
    akapit = "Nasiona pomidora kiełkują najszybciej w temperaturze od 22 do 28 stopni Celsjusza."
    assert not looks_like_noise(akapit)
    assert split_into_paragraphs(akapit) == [akapit]


def test_pusty_tekst_daje_pusta_liste():
    assert split_into_paragraphs("") == []


def test_dzieli_dluga_strone_bez_pustych_linii():
    """Czesc ksiazek wychodzi z PDF-a bez pustych linii - cala strona jako
    jeden ciag. Bez podzialu po zdaniach akapit ma 1800 znakow, cytat
    przestaje wskazywac konkretne miejsce, a podglad daje "gdzies tutaj"."""
    zdanie = "Rozsadę wysiewa się w drugiej połowie marca, gdy gleba jest już rozmarznięta. "
    strona = "\n".join([zdanie.strip()] * 20)

    akapity = split_into_paragraphs(strona)

    assert len(akapity) > 1
    assert all(len(a) <= 750 for a in akapity)


def test_nie_dzieli_w_polowie_zdania():
    """Cytat ma byc czytelny dla czlowieka, ktory zobaczy go w podgladzie."""
    strona = " ".join(
        [
            "Pomidory gruntowe wymagają stanowiska osłoniętego od wiatru i nasłonecznionego przez większą część dnia.",
            "Rozsadę wysiewa się w drugiej połowie marca, a do gruntu sadzi po piętnastym maja.",
            "Optymalny odczyn gleby dla pomidora mieści się w przedziale lekko kwaśnym.",
        ] * 4
    )

    for akapit in split_into_paragraphs(strona):
        assert akapit.rstrip().endswith((".", "!", "?"))


def test_skleja_pojedyncze_zlamania_wiersza():
    text = "Nasiona kiełkują najszybciej\nw temperaturze od 22 do 28 stopni Celsjusza."
    assert split_into_paragraphs(text) == ["Nasiona kiełkują najszybciej w temperaturze od 22 do 28 stopni Celsjusza."]

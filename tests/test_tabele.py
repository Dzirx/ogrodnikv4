"""Tabele z warstwy tekstowej PDF - patrz docs/tabele.md.

`page.get_text()` czyta tabelę wierszami i rozrywa ją na kawałki - te testy
pilnują dwóch rzeczy, które NIE wymagają wywołania modelu: odsiewania
fałszywych wykryć tabeli i zachowania odczytu warstwy tekstowej, gdy model
zawiedzie. Same wywołania (co model odczytał, jak poprawił) sprawdza się na
żywo, nie testem - tak jak reszta modułów opartych na modelu w tym projekcie.
"""

import json

import fitz

from app.ingest.tabele import _prawdziwa_tabela, czy_tabela, odczytaj_tabele


def test_pusta_lista_nie_jest_tabela():
    assert not _prawdziwa_tabela([])


def test_odsiewa_pojedynczy_wiersz():
    """Broszura PODR, strony 6-9: dwie podpisane obok siebie fotografie - PyMuPDF
    widzi pionową kreskę między nimi i zgłasza tabelę 1x2. To nie jest tabela."""
    assert not _prawdziwa_tabela([["Radana", "Black Cherry"]])


def test_odsiewa_wiele_pustych_wierszy():
    assert not _prawdziwa_tabela([[None, None], [None, None]])


def test_akceptuje_tabele_z_wieloma_kolumnami():
    """Liczba kolumn nie jest progiem - program ochrony pomidora ma tabele
    dawek, ktore PyMuPDF dzieli na 23-27 kolumn przez szum w liniach siatki,
    a to nadal ta sama prawdziwa tabela (_tab/, strony 21-24)."""
    wiersze = [["x"] * 23, [None, "y"] + [None] * 21]
    assert _prawdziwa_tabela(wiersze)


def test_akceptuje_gesta_tabele():
    wiersze = [
        ["Środek", "Dawka na ha", "Karencja"],
        ["Sencor Liquid 600 SC", "0,6 l", "42 dni"],
        ["Devrinol 450 S.C.", "2,5-3 l", "nd"],
    ]
    assert _prawdziwa_tabela(wiersze)


def test_strona_bez_kresek_nie_jest_tabela():
    """Strona bez zadnej struktury tabeli - zwykla proza."""
    dokument = fitz.open()
    strona = dokument.new_page()
    strona.insert_text((72, 100), "Pomidory sadzi się po piętnastym maja.", fontsize=11)
    assert not czy_tabela(strona)


class _Wiadomosc:
    def __init__(self, content):
        self.content = content


class _Odpowiedz:
    def __init__(self, payload):
        self.choices = [type("Choice", (), {"message": _Wiadomosc(json.dumps(payload))})]
        self.usage = type("Usage", (), {"total_tokens": 0})


def test_gdy_model_pada_zostaje_odczyt_warstwy_tekstowej(monkeypatch):
    """Model niedostępny nie może zabrać strony calkowicie - gorszy, poszarpany
    akapit z page.get_text() jest lepszy niż strona bez treści."""
    import app.ingest.tabele as tabele

    class Zepsuty:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    raise RuntimeError("model niedostępny")

    monkeypatch.setattr(tabele, "_openai", Zepsuty)

    dokument = fitz.open()
    strona = dokument.new_page()

    assert tabele.odczytaj_tabele(strona, "Sencor 0,6 l   Dawka na ha") == "Sencor 0,6 l   Dawka na ha"


def test_zwraca_blok_z_drugiego_wywolania(monkeypatch):
    """Blok z modelu 2 - a nie surowy odczyt modelu 1 - jest tym, co idzie do
    bazy jako Chunk (patrz "Co trafia do baz" w docs)."""
    import app.ingest.tabele as tabele

    wywolania = []

    class Fake:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    wywolania.append(kwargs)
                    if len(wywolania) == 1:
                        return _Odpowiedz({"naglowki": ["Środek"], "wiersze": [{"komorki": ["Sencor"]}]})
                    return _Odpowiedz({"poprawki": "brak", "blok": "Środek: Sencor Liquid 600 SC"})

    monkeypatch.setattr(tabele, "_openai", Fake)

    dokument = fitz.open()
    strona = dokument.new_page()

    assert tabele.odczytaj_tabele(strona, "tekst warstwy") == "Środek: Sencor Liquid 600 SC"
    assert len(wywolania) == 2


def test_pusty_blok_nie_kasuje_odczytu_warstwy(monkeypatch):
    """Model 2 oddający pusty blok (np. źle sformatowana odpowiedź) nie może
    zamienić dobrego odczytu warstwy tekstowej na pustkę."""
    import app.ingest.tabele as tabele

    wywolania = []

    class Fake:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    wywolania.append(kwargs)
                    if len(wywolania) == 1:
                        return _Odpowiedz({"naglowki": [], "wiersze": []})
                    return _Odpowiedz({"poprawki": "", "blok": ""})

    monkeypatch.setattr(tabele, "_openai", Fake)

    dokument = fitz.open()
    strona = dokument.new_page()

    assert tabele.odczytaj_tabele(strona, "tekst warstwy") == "tekst warstwy"

"""Obraz strony zrodla z podswietlonym cytatem.

Redaktor na spotkaniu 14 wrzesnia: "nie znajduje tego na tej stronie, musze to
znalezc, zeby zrozumiec, gdzie to jest". Sam numer strony nie wystarcza -
ksiazkowa strona ma kilka tysiecy znakow i szukanie na niej jednego zdania to
dokladnie ta praca, ktorej mial nie wykonywac.

Dlatego nie osadzamy PDF-a, tylko renderujemy strone jako obraz z zaznaczonym
fragmentem.
"""

import re

import fitz

SKALA = 2.0  # czytelnosc na ekranie

# Zolty, w bajtach - pixmap operuje na wartosciach 0-255, nie 0-1.
KOLOR_ZAZNACZENIA_RGB = (255, 200, 0)
GRUBOSC_RAMKI = 3

# Ile slow pod rzad wystarczy, zeby uznac miejsce za znalezione.
MINIMUM_SLOW = 8

# Ile obcych slow wolno przeskoczyc w srodku (numer strony, podpis, przypis).
#
# Jeden, nie trzy: przy trzech dopasowanie potrafilo przeskoczyc z konca
# jednego punktu na poczatek nastepnego i zaznaczyc nie te linijke. Zdarza sie
# to, gdy PDF lamie wyraz ("kre da" zamiast "kreda") - cytat urywa sie w tym
# miejscu, a luzna tolerancja pozwala mu "dobiec" do zupelnie innego zdania.
DOPUSZCZALNE_WTRACENIA = 1


def _normalizuj(slowo: str) -> str:
    """Do porownania slow: bez interpunkcji, malymi literami.

    Tekst w PDF-ie ma inne lamanie i czesto twarde dywizy, a nasz akapit jest
    juz sklejony - porownanie znak w znak nie ma szans."""
    return re.sub(r"[^\w]", "", slowo.replace("­", "")).lower()


def _dopasuj_slowa(slowa_strony: list[str], slowa_cytatu: list[str]) -> list[int]:
    """Indeksy slow strony nalezacych do cytatu.

    Zwracamy konkretne slowa, nie zakres "od-do": na marginesie tej ksiazki
    biegnie pionowy tytul rozdzialu, ktorego slowa PyMuPDF wplata w kolejnosc
    czytania. Zaznaczanie calego zakresu braloby je razem z trescia i redaktor
    widzialby zolty pasek przez pol strony.

    Szukanie osobnych krotkich fraz (tak bylo najpierw) jest jeszcze gorsze:
    "wysiewu nasion" trafia w cztery rozne akapity naraz."""
    if not slowa_cytatu or not slowa_strony:
        return []

    najlepsze: list[int] = []
    # Startujemy od pierwszego slowa cytatu; przy remisie dlugosci wygrywa
    # wczesniejsze wystapienie, bo cytat czyta sie od poczatku.
    for start in range(len(slowa_strony)):
        if slowa_strony[start] != slowa_cytatu[0]:
            continue
        dopasowane = [start]
        pozycja_cytatu = 1
        pominiete = 0
        pozycja = start + 1
        while pozycja < len(slowa_strony) and pozycja_cytatu < len(slowa_cytatu) and pominiete <= DOPUSZCZALNE_WTRACENIA:
            if slowa_strony[pozycja] == slowa_cytatu[pozycja_cytatu]:
                dopasowane.append(pozycja)
                pozycja_cytatu += 1
                pominiete = 0
            else:
                pominiete += 1
            pozycja += 1
        if len(dopasowane) > len(najlepsze):
            najlepsze = dopasowane

    # Prog jest staly, nie polowa cytatu. Akapit potrafi miec dziewiecdziesiat
    # slow i przechodzic przez ramke albo lamac sie miedzy kolumnami - wtedy
    # dopasowanie urywa sie po kilkunastu slowach, mimo ze wskazuje dokladnie
    # to miejsce. Wymaganie polowy akapitu kasowalo takie trafienia i redaktor
    # dostawal strone bez zadnego zaznaczenia.
    #
    # Osiem slow pod rzad w tej samej kolejnosci to juz nie przypadek, a
    # zaznaczenie kawalka akapitu i tak prowadzi oko we wlasciwe miejsce.
    if len(najlepsze) < MINIMUM_SLOW:
        return []
    return najlepsze


def render_strony(pdf_bytes: bytes, numer_strony: int, cytat: str | None = None) -> bytes:
    """Zwraca PNG strony. Gdy podano cytat, obrysowuje go na zolto.

    Rysujemy na GOTOWYM OBRAZIE, nie na stronie PDF. Powod jest empiryczny:
    ramka narysowana dokladnie na prostokacie slowa zwroconym przez
    get_text() ladowala w tej ksiazce linijke nizej. Uklad wspolrzednych
    odczytu tekstu i rysowania po stronie rozjezdza sie (mediabox zaczyna sie
    od y=7,83, cropbox od zera), a zgadywanie poprawki jest kruche.

    Na pixmapie przeliczenie jest jednoznaczne: piksel = (punkt - poczatek
    strony) * skala. Nie da sie pomylic ukladow, bo jest tylko jeden.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as dokument:
        if not 1 <= numer_strony <= dokument.page_count:
            raise ValueError(f"strona {numer_strony} nie istnieje")
        strona = dokument[numer_strony - 1]

        prostokaty: list[tuple[float, float, float, float]] = []
        if cytat:
            slowa = strona.get_text("words")
            znormalizowane = [_normalizuj(w[4]) for w in slowa]
            indeksy = _dopasuj_slowa(znormalizowane, [_normalizuj(w) for w in cytat.split() if _normalizuj(w)])
            prostokaty = [tuple(slowa[i][:4]) for i in indeksy]

        obraz = strona.get_pixmap(matrix=fitz.Matrix(SKALA, SKALA))
        poczatek = strona.rect

    for x0, y0, x1, y1 in prostokaty:
        _obrysuj(obraz, x0 - poczatek.x0, y0 - poczatek.y0, x1 - poczatek.x0, y1 - poczatek.y0)

    return obraz.tobytes("png")


def _obrysuj(obraz, x0: float, y0: float, x1: float, y1: float) -> None:
    """Zolta ramka wokol slowa, na pixmapie.

    Ramka, nie wypelnienie: pixmap nie ma przezroczystosci, wiec wypelnienie
    zamalowaloby tekst, ktory redaktor ma przeczytac."""
    lewo, gora = int(x0 * SKALA), int(y0 * SKALA)
    prawo, dol = int(x1 * SKALA), int(y1 * SKALA)
    lewo, gora = max(0, lewo), max(0, gora)
    prawo, dol = min(obraz.width, prawo), min(obraz.height, dol)
    if prawo <= lewo or dol <= gora:
        return

    for y in (gora, dol - GRUBOSC_RAMKI):
        obraz.set_rect(fitz.IRect(lewo, y, prawo, y + GRUBOSC_RAMKI), KOLOR_ZAZNACZENIA_RGB)
    for x in (lewo, prawo - GRUBOSC_RAMKI):
        obraz.set_rect(fitz.IRect(x, gora, x + GRUBOSC_RAMKI, dol), KOLOR_ZAZNACZENIA_RGB)

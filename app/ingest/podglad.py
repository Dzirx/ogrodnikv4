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

# Ile punktow dokladamy nad i pod cytatem. Musi byc wieksze niz obserwowane
# przesuniecie renderu (okolo 20 punktow), zeby cytat na pewno zostal w kadrze,
# i na tyle duze, zeby bylo widac kontekst - sasiednie zdania.
ZAPAS = 70

# Fragment jest mniejszy niz cala strona, wiec moze byc renderowany dokladniej.
SKALA_FRAGMENTU = 3.0

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
    """Zwraca PNG strony, a przy podanym cytacie - sam fragment wokol niego.

    Nie rysujemy ramki. Probowalem tego dlugo i nie dziala: w tej ksiazce
    render jest przesuniety wzgledem wspolrzednych z get_text o okolo dwadziescia
    punktow, czyli linijke. Sprawdzone trzema sposobami - rysowaniem po stronie,
    adnotacja PDF i rysowaniem po gotowym obrazie - wszystkie ladowaly w tym
    samym zlym miejscu, wiec przyczyna lezy w samych wspolrzednych, nie w
    sposobie rysowania. Nie wynika ani z mediabox, ani z cropbox.

    Zamiast zgadywac poprawke, ktora i tak byla by krucha dla innych ksiazek,
    WYCINAMY fragment strony wokol cytatu z zapasem. Zapas pochlania blad:
    nawet przesuniety o linijke cytat zostaje w kadrze, a redaktor widzi
    powiekszony kawalek ksiazki zamiast calej strony. Sam cytat jest przy tym
    podswietlony w tekscie obok (patrz app/api/routes.py::_rozbij_na_cytat),
    wiec wiadomo, ktore zdanie czytac.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as dokument:
        if not 1 <= numer_strony <= dokument.page_count:
            raise ValueError(f"strona {numer_strony} nie istnieje")
        strona = dokument[numer_strony - 1]

        obszar = None
        if cytat:
            slowa = strona.get_text("words")
            znormalizowane = [_normalizuj(w[4]) for w in slowa]
            indeksy = _dopasuj_slowa(znormalizowane, [_normalizuj(w) for w in cytat.split() if _normalizuj(w)])
            if indeksy:
                gora = min(slowa[i][1] for i in indeksy)
                dol = max(slowa[i][3] for i in indeksy)
                obszar = fitz.Rect(
                    strona.rect.x0,
                    max(strona.rect.y0, gora - ZAPAS),
                    strona.rect.x1,
                    min(strona.rect.y1, dol + ZAPAS),
                )

        skala = SKALA_FRAGMENTU if obszar else SKALA
        return strona.get_pixmap(matrix=fitz.Matrix(skala, skala), clip=obszar).tobytes("png")

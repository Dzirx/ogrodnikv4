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

    for start in range(len(slowa_strony)):
        if slowa_strony[start] != slowa_cytatu[0]:
            continue
        dopasowane = [start]
        pozycja_cytatu = 1
        pominiete = 0
        pozycja = start + 1
        while pozycja < len(slowa_strony) and pozycja_cytatu < len(slowa_cytatu) and pominiete <= 3:
            if slowa_strony[pozycja] == slowa_cytatu[pozycja_cytatu]:
                dopasowane.append(pozycja)
                pozycja_cytatu += 1
                pominiete = 0
            else:
                pominiete += 1
            pozycja += 1
        if len(dopasowane) > len(najlepsze):
            najlepsze = dopasowane

    # Ponizej polowy cytatu uznajemy, ze to nie jest to miejsce - lepiej nie
    # zaznaczyc nic niz wskazac zly akapit.
    if len(najlepsze) < max(4, len(slowa_cytatu) // 2):
        return []
    return najlepsze


def render_strony(pdf_bytes: bytes, numer_strony: int, cytat: str | None = None) -> bytes:
    """Zwraca PNG strony. Gdy podano cytat, zaznacza go na zolto."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as dokument:
        if not 1 <= numer_strony <= dokument.page_count:
            raise ValueError(f"strona {numer_strony} nie istnieje")
        strona = dokument[numer_strony - 1]

        if cytat:
            slowa = strona.get_text("words")  # (x0, y0, x1, y1, slowo, ...)
            znormalizowane = [_normalizuj(w[4]) for w in slowa]
            indeksy = _dopasuj_slowa(znormalizowane, [_normalizuj(w) for w in cytat.split() if _normalizuj(w)])
            for indeks in indeksy:
                x0, y0, x1, y1 = slowa[indeks][:4]
                podswietlenie = strona.add_highlight_annot(fitz.Rect(x0, y0, x1, y1))
                podswietlenie.set_colors(stroke=(1, 0.92, 0.23))
                podswietlenie.update()

        return strona.get_pixmap(matrix=fitz.Matrix(SKALA, SKALA)).tobytes("png")

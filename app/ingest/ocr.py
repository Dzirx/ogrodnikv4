"""Odczyt stron, na ktorych tekst siedzi w obrazie.

Klient przecina grzbiety ksiazek i przepuszcza je przez skaner - mowil to
wprost na spotkaniu. Taka ksiazka wchodzila dotad jako "gotowa" z zerowa
liczba akapitow, bez jednego slowa ostrzezenia.

Tesseract, nie model wizyjny. Model wizyjny czyta strukture lepiej, ale
ZMYSLA: przy tabelach robil z "Hadican" - "Hadcam", a w dluzszym tekscie
dopisywal slowa, ktorych nie ma. Tesseract myli litery (polskie znaki: l na t,
z na z), ale nie wymysla zdan - blad, ktory widac, jest lepszy od bledu,
ktorego nie widac.
"""

import re
import subprocess

import fitz

# Ponizej tej pewnosci strona jest obrazem, nie tekstem. Zmierzone na
# ksiazkach klienta: fotografia krzewow 31%, zdjecie owocu 45%, strona
# tytulowa 90,6%, stopka z adresem 92,6%.
#
# Bylo 65 i okazalo sie za nisko: okladka PODR przeszla z wynikiem 70,2%,
# a odczyt to w wiekszosci szum obok poprawnie odczytanej nazwy instytucji.
#
# To jest stala JAKOSCI ODCZYTU, nie stala ksiazki - dlatego przeniesie sie na
# nastepne pliki. Progu "ile znakow ma miec strona" celowo nie ma: ksiazka
# z gestym skladem ma ich dwa tysiace, album ze zdjeciami dwiescie, a jedna
# liczba w kodzie bylaby zla dla ktorejs z nich.
MIN_PEWNOSC = 80

# Ponizej tej pewnosci pojedyncze slowo jest smieciem, nawet gdy cala strona
# czyta sie dobrze. Na okladce nazwa instytucji wyszla poprawnie, a szum wokol
# niej - nie; srednia po calej stronie tego nie rozdziela.
MIN_PEWNOSC_SLOWA = 60

# Rozdzielczosc renderu do OCR. Ponizej 300 dpi Tesseract gubi ogonki.
DPI = 300

# Sufit na dluzszy bok obrazu. A4 w 300 dpi ma 3508 pikseli, wiec zwykla strona
# go nie dotyka. Chroni przed PDF-em o nietypowych wymiarach: strona zapisana
# w punktach rownych pikselom skanu dala obraz 6900x9700 i Tesseract czytal ja
# 215 sekund zamiast osiemnastu.
MAX_PIKSELI = 3600

# Ile stron czytamy naraz. Tesseract idzie osobnym procesem, wiec czekamy
# tylko na wejscie-wyjscie i watki wystarcza.
RAZEM_STRON = 4


def zrzut_strony(strona: fitz.Page, obszar: fitz.Rect | None = None) -> bytes:
    """Strona jako obraz PNG. WYLACZNIE z watku glownego.

    PyMuPDF nie jest bezpieczny wielowatkowo - siegniecie po ten sam dokument
    z czterech watkow naraz zawieszalo przetwarzanie na tyle, ze cztery strony
    nie skonczyly sie w dziewiec minut. Renderujemy wiec po kolei (to jest
    szybkie), a rownolegle idzie tylko Tesseract, ktory jest osobnym procesem."""
    prostokat = obszar or strona.rect
    dluzszy_bok = max(prostokat.width, prostokat.height) / 72  # w calach
    dpi = min(DPI, int(MAX_PIKSELI / dluzszy_bok)) if dluzszy_bok else DPI
    return strona.get_pixmap(dpi=max(dpi, 72), clip=obszar).tobytes("png")


def odczytaj_png(png: bytes) -> tuple[str, float]:
    """Tekst odczytany z obrazu i srednia pewnosc odczytu (0-100)."""
    wynik = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "pol", "--psm", "6", "tsv"],
        input=png,
        capture_output=True,
    )
    if wynik.returncode != 0:
        return "", 0.0

    slowa: list[str] = []
    pewnosci: list[float] = []
    for linia in wynik.stdout.decode("utf-8", "replace").splitlines()[1:]:
        pola = linia.split("\t")
        if len(pola) < 12 or not pola[11].strip():
            continue
        try:
            pewnosc = float(pola[10])
        except ValueError:
            continue
        pewnosci.append(pewnosc)
        # Smiecie odsiewamy slowo po slowie, nie srednia po stronie.
        if pewnosc >= MIN_PEWNOSC_SLOWA:
            slowa.append(pola[11].strip())

    if not pewnosci:
        return "", 0.0
    return " ".join(slowa), sum(pewnosci) / len(pewnosci)


def odczytaj_obraz(strona: fitz.Page, obszar: fitz.Rect | None = None) -> tuple[str, float]:
    """Wygoda dla pojedynczej strony: zrzut i odczyt za jednym zamachem."""
    return odczytaj_png(zrzut_strony(strona, obszar))


def _pokrycie(prostokaty: list[fitz.Rect], strona: fitz.Page) -> float:
    """Jaka czesc strony zajmuja podane prostokaty."""
    pole = strona.rect.width * strona.rect.height
    if pole <= 0:
        return 0.0
    return sum(p.width * p.height for p in prostokaty) / pole


def gdzie_jest_tekst(strona: fitz.Page) -> tuple[float, float]:
    """Jaka czesc strony pokrywa tekst, a jaka obrazy.

    Pytamy o to, GDZIE na stronie jest tresc, a nie "czy to jest skan".
    Ta sama reguła obsluguje ksiazke tekstowa, skan i mieszana."""
    bloki = [fitz.Rect(b[:4]) for b in strona.get_text("blocks") if len(b) > 4 and b[4].strip()]
    obrazy = [r for info in strona.get_images() for r in strona.get_image_rects(info[0])]
    return _pokrycie(bloki, strona), _pokrycie(obrazy, strona)


_SLOWO = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def ma_tresc(tekst: str) -> bool:
    """Czy odczyt niesie cokolwiek, co da sie zacytowac."""
    return len(_SLOWO.findall(tekst)) >= 10

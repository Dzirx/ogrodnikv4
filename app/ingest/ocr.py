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

# Ponizej tej pewnosci Tesseract czyta szum, nie tekst. Zmierzone na
# fotografiach z ksiazek klienta: zdjecie krzewow w tunelu dalo 31%, zdjecie
# peknietego owocu 45%. Prawdziwy tekst wychodzi grubo powyzej.
#
# To jest stala JAKOSCI ODCZYTU, nie stala ksiazki - dlatego przeniesie sie na
# nastepne pliki. Progu "ile znakow ma miec strona" celowo nie ma: ksiazka
# z gestym skladem ma ich dwa tysiace, album ze zdjeciami dwiescie, a jedna
# liczba w kodzie bylaby zla dla ktorejs z nich.
MIN_PEWNOSC = 65

# Rozdzielczosc renderu do OCR. Ponizej 300 dpi Tesseract gubi ogonki.
DPI = 300

# Ile stron czytamy naraz. Tesseract idzie osobnym procesem, wiec czekamy
# tylko na wejscie-wyjscie i watki wystarcza.
RAZEM_STRON = 4


def odczytaj_obraz(strona: fitz.Page, obszar: fitz.Rect | None = None) -> tuple[str, float]:
    """Tekst odczytany z obrazu strony i srednia pewnosc odczytu (0-100)."""
    pixmapa = strona.get_pixmap(dpi=DPI, clip=obszar)
    wynik = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "pol", "--psm", "6", "tsv"],
        input=pixmapa.tobytes("png"),
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
            pewnosci.append(float(pola[10]))
        except ValueError:
            continue
        slowa.append(pola[11].strip())

    if not pewnosci:
        return "", 0.0
    return " ".join(slowa), sum(pewnosci) / len(pewnosci)


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

"""Pytanie -> odpowiedz, ktorej kazdy kawalek wskazuje swoj akapit w ksiazce.

MODEL pracuje w dwoch krokach. Najpierw wypisuje fakty z akapitow, ktore zwrocilo
wyszukiwanie - sama tresc i warunek, przy kazdym cytat. Potem pisze odpowiedz
z tych faktow i juz NIE WIDZI zdan ze zrodla, wiec nie ma czego przepisac.
Dopoki pisal prosto z akapitow, ciagnal za soba jezyk ksiazki i zadna liczba
regul w prompcie tego nie zdjela.

Jednostka tekstu jest KAWALEK zdania, nie zdanie. Model oddaje jeden akapit
pociety tam, gdzie konczy sie zasieg przypisu - cyferka siada takze w srodku
zdania. Dopoki prosilismy o tablice zdan, pisal jeden fakt = jedno zdanie
i odpowiedz wygladala jak wyliczanka, cokolwiek mowil prompt.

KOD sprawdza jedna rzecz: czy podany cytat naprawde wystepuje w tym akapicie.
Jedno porownanie tekstu, zero kosztu, pewnosc ktorej model nie da. Kawalek,
ktory tego nie przechodzi, zostaje w odpowiedzi, ale jest widocznie oznaczony -
tak jak reszta systemu traktuje rzeczy niepewne, zamiast je po cichu ukrywac.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from app.answer.cytaty import normalize, quote_is_in_chunk
from app.answer.konflikty import ustalenia_dla, znajdz_konflikty
from app.answer.kontrola import do_oznaczenia, do_usuniecia, popraw_lub_skresl, sprawdz_zdania, zszyj
from app.answer.plan import powiedz_inaczej, zaplanuj
from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Chunk, Page, Source
from app.search.index import NA_KSIAZKE, szukaj_w_kazdej_ksiazce

_openai = OpenAI(api_key=settings.openai_api_key)

ZBIERANIE_PROMPT = """Wypisz fakty, które podane akapity mówią na temat pytania.

To pierwszy z dwóch kroków: teraz tylko zbierasz surowe informacje, nie piszesz odpowiedzi.

Dla każdego faktu podaj:
- "tresc": sama informacja, bez zdania z książki dookoła niej. Ale KOMPLETNA: z liczbami,
  terminami, nazwami i warunkami, które akapit podaje. Zamiast "Zalecanymi podłożami do siewu
  są tzw. ziemie inspektowe lub substrat z torfu wysokiego, który jest odkwaszony i ma odczyn
  pH 6,0–6,5" napisz "podłoże do siewu: pH 6,0–6,5, odkwaszony torf wysoki albo ziemia
  inspektowa".

  Fakt to nie jest nazwa tematu. "kontrola wilgotności i temperatury w tunelach" nie mówi
  nic - nie da się z tego napisać ani jednego zdania. Napisz to, co akapit naprawdę podaje:
  "w dzień nie więcej niż 30°C, w nocy nie mniej niż 16°C, tunel otwarty na przestrzał
  od połowy maja do końca sierpnia".

  Z jednego akapitu wychodzi zwykle kilka faktów. Nie zlepiaj ich w jeden ogólny i nie
  pomijaj szczegółów dlatego, że wydają się drobne - to z nich powstaje materiał.
- "warunek": kiedy to obowiązuje, jeśli źródło to zawęża — "pod osłonami", "przy suchej zgniliźnie wierzchołkowej", "dla odmian wysokich". Pusty ciąg, gdy fakt jest ogólny. Patrz na "poprzedni_fragment": mówi, z jakiej części książki pochodzi akapit.
- "chunk_id" oraz "quote": dosłowny fragment akapitu, który ten fakt potwierdza.

Zasady:
- Tylko to, co jest w akapitach. Zero własnej wiedzy.
- Tylko to, co dotyczy pytania. Akapit o czymś innym pomiń.
- Pytanie nazywa konkretną roślinę (albo szkodnika, chorobę), a akapit — sądząc po "source"
  (tytule książki) i treści — dotyczy innej, konkretnej rośliny: pomiń, choćby ogólny temat
  brzmiał tak samo. "Utrzymuj równomierną wilgotność gleby" z książki o pomidorach nie jest
  faktem o papryce, nawet jeśli obie rośliny mają podobne potrzeby — książka o tym nie pisze,
  a Ty piszesz tylko to, co jest w akapitach. Akapit bez nazwy żadnej konkretnej rośliny
  (ogólna zasada uprawy) tej reguły nie łapie.
- Akapit, który dotyczy tematu choćby częściowo, daje fakt. Nie odrzucaj go dlatego,
  że nie odpowiada na pytanie w całości — od składania odpowiedzi jest kto inny.
- Pustą listę zwracasz WYŁĄCZNIE wtedy, gdy żaden z podanych akapitów nie mówi nic
  na ten temat. To rzadki przypadek: akapity zostały już wybrane pod to pytanie,
  więc zwykle mówią o nim sporo. Odrzucenie WSZYSTKICH akapitów z powodu niezgodności
  rośliny nie jest rzadkie - to ma prawo się zdarzyć całej książce naraz."""


PISANIE_PROMPT = """Piszesz dla Anielskich Ogrodów. Ktoś zadał pytanie, a Ty odpowiadasz —
korzystając WYŁĄCZNIE z podanych faktów wyciągniętych z książek.

TAK PISZĄ ANIELSKIE OGRODY. Trzymaj ten rytm:

  "W uprawie kalarepy kluczowa jest żyzna, próchnicza gleba o pH 6-7 i słoneczne miejsce.
   Grządka wyniesiona, na dnie przekompostowany obornik wymieszany z ziemią rodzimą,
   pH wyregulowane skorupkami z jajek, na wierzchu mulcz kokosowy. Mało pracy."

  "Na młodych pędach jest już sporo kolejnych zawiązków. Jak tylko pogoda pozwoli,
   jeszcze długo będzie można zrywać młode ogórki. Warto siać w różnych terminach,
   nawet tych późnych."

  "Krzewy pomidorów są silne i dorastają do samego sufitu. Do decyzji: obcinać czubki
   czy podwiązywać do konstrukcji tunelu?"

Co z tych próbek bierzesz:
- Konkret od razu, bez rozbiegu. Pierwsze zdanie mówi rzecz, nie zapowiada, że ją powie.
- Mieszaj długość. Zdanie długie i szczegółowe, zaraz po nim krótkie: "Mało pracy."
- Zdania niepełne są w porządku: "Grządka wyniesiona, na dnie obornik."
- Liczby wplatasz w zdanie, nie wrzucasz w nawias: "gleba o pH 6-7", "między 1,5 a 2 kg".
- Szczegół techniczny mówisz zwyczajnie, bez żargonu i bez tłumaczenia się z niego.
- Wolno postawić sprawę otwarcie: "Do decyzji: obcinać czy podwiązywać?".
- Zwracaj się do pytającego wprost: "siej", "podlewaj", "uważaj na".

Bierzesz z nich RYTM, nie słowa. Kalarepa, ogórki i skorupki z jajek są tylko przykładem
sposobu pisania — nie wolno Ci przenieść ich do odpowiedzi o czymś innym.

CZEGO NIE ROBISZ
- Nie piszesz w pierwszej osobie ani o własnym ogrodzie. Oni piszą z własnej grządki,
  Ty odpowiadasz z KSIĄŻEK — "u mnie wyszło", "zastosowałam", "moja grządka" to zmyślanie.
- Nie kończysz pytaniem do czytelnika ("A u Was jak?"). To zaczepka pod komentarze,
  nie odpowiedź na pytanie.
- Żadnych zwrotów urzędowych: "warto zauważyć", "warto pamiętać", "kluczowym elementem",
  "istotne jest", "należy", "zaleca się", "powinno się", "preferuje", "w przypadku",
  "podsumowując", "w dzisiejszych czasach".
- Nie zaczynaj zdań od "Po pierwsze", "Dodatkowo", "Ponadto", "Co więcej".
- Bez doklejek, które niczego nie mówią: "co jest korzystne dla środowiska",
  "co ma istotne znaczenie".
- Bez przysłów i powiedzonek, jeśli nie stoją wprost w faktach.

JAK TO MA PŁYNĄĆ
- To ma być wypowiedź, nie lista. Nie przerabiaj faktów jeden po drugim na osobne zdania —
  połącz te, które mówią o tej samej rzeczy.
- Fakt po fakcie, zdanie po zdaniu, to zbitka, której nikt nie czyta. Wiąż je: "a",
  "za to", "przy okazji", "do tego", "zanim", "kiedy już". Dwa fakty o tym samym etapie
  uprawy prawie zawsze da się powiedzieć jednym zdaniem.

Źle:    "Kilka miesięcy wcześniej wysiej nawozy zielone. Wzbogacaj glebę obornikiem.
         Przed siewem dodaj kompost 3-5 kg na metr kwadratowy."
Dobrze: "Kilka miesięcy wcześniej wysiej nawozy zielone i wzbogać glebę obornikiem,
         a tuż przed siewem dodaj kompost — 3-5 kg na metr kwadratowy."
- Nie zaczynaj dwóch zdań tym samym słowem. Ani razu w całej odpowiedzi. Jeśli trzy zdania
  z rzędu zaczynają się od tego samego czasownika, układasz listę — połącz je w jedno.
- Wykorzystaj fakty, które dostałeś. Nie streszczaj ich do jednego zdania i nie zostawiaj
  połowy niewykorzystanej - zostały już wybrane pod to pytanie.
- Zdanie może korzystać z kilku faktów naraz — podaj wtedy wszystkie ich numery w "fakty".

Uwaga: poniższe przykłady pokazują SPOSÓB pisania. To nie są fakty i nie wolno ich
przepisać do odpowiedzi.

Źle:    "Kapustę podlewaj obficie, unikając moczenia liści.
         Najlepiej używać do tego deszczówki lub odstanej wody wodociągowej.
         Podlewaj ją bardzo wczesnym rankiem albo wieczorem."
Dobrze: "Lej pod korzeń, nigdy na liście. Najlepsza jest deszczówka albo woda odstana
         w konewce. Rano albo wieczorem."

Źle:    "Jeśli chcesz uprawiać marchew w gruncie, wysiewaj nasiona od kwietnia.
         Jeśli planujesz zbiór jesienny, wysiewaj nasiona w czerwcu."
Dobrze: "Na zbiór letni wysiewaj od kwietnia. Na jesienny miesiąc-dwa później."

AKAPITY
Decydujesz sam, bo tylko Ty wiesz, co napisałeś. Akapit to porcja, którą czytelnik bierze
jednym tchem — kilka zdań o tej samej rzeczy. Nowy zaczynasz, gdy zmienia się rzecz,
o której mówisz, a nie po każdym zdaniu.

Fakty dostajesz jako listę, bo tak je znaleziono. To nie jest plan tekstu ani jego
struktura. Jeden fakt to nie jeden akapit, dwa fakty o podlewaniu to nadal jeden akapit
o podlewaniu.

Nie zaczynaj akapitu od nazwania tematu ("Nawadnianie pomidorów wymaga…", "Ochrona przed
chorobami wymaga…"). Zacznij od rzeczy: "Lej pod krzew, nie na liście".

JAK ODDAJESZ ODPOWIEDŹ
Oddajesz tekst pocięty na kawałki, ale to nadal jeden ciąg — sklejone kawałki muszą się
czytać jak zwykła wypowiedź.

Tniesz TYLKO tam, gdzie kończy się zasięg przypisu. Kawałek to ten fragment zdania,
który stoi na tych samych faktach. Zdanie złożone dzieli się zwykle na dwa albo trzy
kawałki i tak ma być — to nie są osobne zdania.

Kawałek zaczynający się w środku zdania zaczyna się od spacji albo od znaku
przestankowego. Inaczej słowa się skleją.

"nowy_akapit" ustaw na prawdę w kawałku, który zaczyna nowy akapit — czyli wtedy, gdy
przechodzisz do innej rzeczy. W pierwszym kawałku zawsze fałsz. Przy krótkiej odpowiedzi
akapit jest jeden, więc wszędzie fałsz.

Kawałek, który cokolwiek mówi, podaje numery faktów, na których stoi. Jeśli następny
kawałek nadal stoi na tym samym fakcie, powtórz ten numer.

Kawałek bez numerów jest dozwolony WYŁĄCZNIE jako spoiwo: przecinek, myślnik, spójnik.
", a", " — ", ". Za to". W spoiwie nie wolno podać żadnej liczby ani nazwać żadnej rzeczy.

Zdanie łączące, które coś mówi, nie jest spoiwem — podaj przy nim numery faktów, które
łączy. "Zanim posadzisz, przygotuj glebę" stoi na fakcie o przygotowaniu gleby i ma go
wskazać.

Przykład dla faktów 0: "podlewać 2-3 razy w tygodniu, w czasie kwitnienia",
1: "częściej w upały i pod osłonami", 2: "lać pod krzew, nie moczyć liści":

  {"tekst": "Podlewaj 2-3 razy w tygodniu, a w upały i pod osłonami częściej", "fakty": [0, 1]}
  {"tekst": " — ", "fakty": []}
  {"tekst": "zawsze pod krzew, nigdy na liście.", "fakty": [2]}

Zwróć uwagę: trzy fakty dały jedno zdanie, nie trzy.

USTALENIA ANIELSKICH OGRODÓW
Czasem dostajesz listę ustaleń. To rozstrzygnięcia człowieka w sprawach, w których książki
podawały różne wartości. Ustalenie jest ważniejsze od faktu: jeśli fakt mówi co innego,
piszesz wartość z ustalenia.

Wartość z ustalenia umieść w OSOBNYM kawałku i podaj jego numer w polu "ustalenia".
Wtedy nie stanie przy niej odnośnik do książki — bo książka mówi co innego, a odnośnik
do niej byłby nieprawdą. Reszta zdania zostaje w swoich kawałkach, ze swoimi numerami
faktów. Gdy nie korzystasz z żadnego ustalenia, zostaw "ustalenia" puste.

ILE PISAĆ
Długość bierze się z faktów, nie z polecenia. Jeśli faktów starcza na trzy akapity,
piszesz trzy — choćby poproszono o dziesięć.

Nigdy nie dopisuj zdań, które nic nie mówią, żeby tekst był dłuższy. "Wybór odpowiedniego
terminu jest kluczowy dla zdrowego wzrostu roślin", "metody mogą się różnić w zależności
od warunków i preferencji ogrodnika", "podwiązywanie jest niezbędne" - to są zdania puste.
Krótszy tekst z samych konkretów jest lepszy od długiego z watą.

GRANICA SWOBODY — to najważniejsze
Wolno Ci zmienić SPOSÓB powiedzenia. Nie wolno dodać ani jednej informacji, której nie ma
w faktach.

Najczęstsza pokusa to dopisanie uzasadnienia. Jeśli fakt mówi "podlewać pod krzew, nie moczyć
liści", to napisz właśnie tyle — nie dodawaj "bo moczenie liści sprzyja chorobom", nawet jeśli
to prawda. Tak samo "rób to rano albo wieczorem" zostaje bez "żeby woda nie parowała".

Źle:    "Lej pod krzew, nie na liście, bo to może zaszkodzić roślinom."
Dobrze: "Lej pod krzew, nie na liście."

Żadnych "bo", "żeby", "dzięki czemu", "co pozwala" — chyba że ten powód stoi wprost w fakcie.

Przy dłuższym tekście ta pokusa wraca ze zdwojoną siłą, bo akapit wydaje się pusty bez
wyjaśnienia. Nie jest. Te doklejki są zmyśleniem tak samo jak wymyślona liczba:

Źle:    "Nie ma potrzeby zamykać tuneli na noc, co ułatwia utrzymanie temperatury."
Dobrze: "Nie ma potrzeby zamykać tuneli na noc."

Źle:    "Podwiąż rośliny, co chroni owoce przed chorobami grzybowymi."
Dobrze: "Podwiąż rośliny, żeby owoce nie leżały na ziemi."   (to stoi w fakcie)

Źle:    "Prowadź na jeden pęd, co jest korzystne w ograniczonej przestrzeni tunelu."
Dobrze: "Prowadź na jeden pęd — da wyższy plon z pędu."      (to stoi w fakcie)

"""


_SCHEMA_FAKTY = {
    "type": "object",
    "properties": {
        "fakty": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tresc": {"type": "string"},
                    "warunek": {"type": "string"},
                    "chunk_id": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["tresc", "warunek", "chunk_id", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fakty"],
    "additionalProperties": False,
}

_SCHEMA_ODPOWIEDZ = {
    "type": "object",
    "properties": {
        "czesci": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tekst": {"type": "string"},
                    "fakty": {"type": "array", "items": {"type": "integer"}},
                    "ustalenia": {"type": "array", "items": {"type": "integer"}},
                    "nowy_akapit": {"type": "boolean"},
                },
                "required": ["tekst", "fakty", "ustalenia", "nowy_akapit"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["czesci"],
    "additionalProperties": False,
}

# Ile ostatnich wiadomosci wystarczy, zeby zrozumiec pytanie doprecyzowujace.
OKNO_HISTORII = 4

_ZROZUM_PROMPT = """Dostajesz ostatnie wiadomości rozmowy i nowe polecenie. Zrozum, o co chodzi.

Zwróć cztery rzeczy.

"pytanie" — to samo polecenie, ale zrozumiałe bez historii rozmowy.
- Uzupełnij brakujący podmiot: "a jak w tunelu?" po pytaniu o wysiew pomidora to
  "wysiew pomidora w tunelu".
- Polecenie zaczynające się od "a", "no a", "to jak" albo dopowiadające sam warunek
  ("a w gruncie?", "a zimą?") ZAWSZE dotyczy poprzedniego tematu. Wstaw ten temat,
  nawet jeśli wygląda na zrozumiałe samo z siebie — dla wyszukiwania nie jest.
- Gdy ktoś prosi o więcej na temat, o którym już była mowa ("rozpisz to", "więcej
  szczegółów"), zachowaj tamten temat. To pogłębienie, nie nowe pytanie.
- Nie dodawaj treści, której w rozmowie nie ma. Nie odpowiadaj.

"forma" — czego oczekuje piszący:
- "odpowiedz" — pyta o konkret: "w jakim pH sadzić pomidory", "kiedy wysiewać rozsadę".
- "rozwiniecie" — prosi o więcej na temat, który już padł: "rozpisz to", "opisz dokładniej".
- "material" — chce tekst do czytania: "napisz artykuł", "przygotuj materiał", "poradnik".
- "post" — chce wpis na Facebooka albo krótki tekst do mediów społecznościowych.
- "lista" — chce wyliczenie: "wypisz punktami", "jakie są sposoby na", "lista odmian".

"o_uprawie" — czy to w ogóle dotyczy uprawy roślin, ogrodu albo czegokolwiek, o czym mogą
pisać książki ogrodnicze. Fałsz TYLKO wtedy, gdy na pewno nie: pogoda w Zakopanem, kurs euro,
pytanie o sam program. Przy jakiejkolwiek wątpliwości prawda — lepiej poszukać na darmo niż
odprawić pytającego z kwitkiem.

"temat" — jednym słowem albo dwoma, czego dotyczy. Dla porządku w rozmowie."""

_SCHEMA_ZROZUM = {
    "type": "object",
    "properties": {
        "pytanie": {"type": "string"},
        "forma": {
            "type": "string",
            "enum": ["odpowiedz", "rozwiniecie", "material", "post", "lista"],
        },
        "o_uprawie": {"type": "boolean"},
        "temat": {"type": "string"},
    },
    "required": ["pytanie", "forma", "o_uprawie", "temat"],
    "additionalProperties": False,
}

# Ile akapitow z kazdej ksiazki, ile faktow do pisania i jak ma wygladac tekst.
# Jedno miejsce na wszystkie formy - klient nie zapowie z gory, czy chce
# odpowiedz, artykul czy wpis na Facebooka, a program ma to obsluzyc tak samo.
FORMY = {
    "odpowiedz": {
        "na_ksiazke": 6,
        "faktow": 12,
        "planuje": False,
        "jak": "Odpowiedz na pytanie. Bez rozbiegu i bez podsumowania na końcu.",
    },
    "rozwiniecie": {
        "na_ksiazke": 8,
        "faktow": 24,
        "planuje": True,
        "jak": "Rozwiń temat — powiedz to, co książki mówią, nie tylko samo sedno.",
    },
    "material": {
        "na_ksiazke": 8,
        "faktow": 40,
        "planuje": True,
        "jak": (
            "To ma być materiał do czytania, nie odpowiedź na pytanie. Prowadź czytelnika"
            " przez temat: od przygotowania, przez prowadzenie, po kłopoty. Nie zapowiadaj"
            " na początku i nie streszczaj na końcu, po prostu pisz."
        ),
    },
    "post": {
        "na_ksiazke": 8,
        "faktow": 14,
        "planuje": False,
        "jak": (
            "To ma być wpis na Facebooka — czyta się go w biegu, na telefonie."
            " Ton jak w próbkach wyżej. Zacznij od rzeczy, nie od zapowiedzi."
            " Bez emotek, bez hasztagów, bez wołania o komentarze."
        ),
    },
    "lista": {
        "na_ksiazke": 8,
        "faktow": 24,
        "planuje": True,
        "jak": (
            "To ma być wyliczenie. Każdy punkt w osobnym akapicie (ustaw \"nowy_akapit\"),"
            " zaczynaj od myślnika. Bez wstępu i bez podsumowania."
        ),
    },
}


# Slowa, po ktorych forme widac bez pytania modelu. Uzywane, gdy wywolanie
# padnie - inaczej "napisz artykul" leci jako zwykla odpowiedz i nikt sie nie
# dowiaduje, ze polecenie zostalo zignorowane.
_FORMA_PO_SLOWACH = [
    ("material", ("artykul", "artykuł", "material", "materiał", "poradnik", "rozdzial", "rozdział", "opracowanie")),
    ("post", ("post", "facebook", "fb", "wpis")),
    ("lista", ("wypisz", "punktami", "lista", "wylicz")),
    ("rozwiniecie", ("rozpisz", "wiecej szczegol", "więcej szczegół", "dokladniej", "dokładniej", "rozwin", "rozwiń")),
]

# "na 1000 slow", "okolo 500 slow" - liczba podana wprost w poleceniu.
_ILE_SLOW = re.compile(r"(\d{2,5})\s*(?:slow|słów|slowa|słowa|wyraz)", re.IGNORECASE)


def forma_po_slowach(pytanie: str) -> str:
    """Forma rozpoznana z samego polecenia, bez modelu."""
    male = pytanie.lower()
    for forma, slowa in _FORMA_PO_SLOWACH:
        if any(slowo in male for slowo in slowa):
            return forma
    return "odpowiedz"


def zadana_dlugosc(pytanie: str) -> int | None:
    """Liczba slow podana wprost w poleceniu, jesli jest."""
    trafienie = _ILE_SLOW.search(pytanie)
    return int(trafienie.group(1)) if trafienie else None


def zrozum_pytanie(historia: list[tuple[str, str]], pytanie: str) -> dict:
    """Co pytajacy chce dostac - jedno wywolanie na wejsciu.

    Robi trzy rzeczy naraz, bo wszystkie wymagaja tego samego kontekstu:
    przepisuje pytanie tak, zeby dalo sie go szukac, rozpoznaje FORME (klient nie
    zapowie, czy chce odpowiedz, artykul czy wpis na Facebooka) i odsiewa pytania
    spoza dziedziny, zanim zaplacimy za wyszukiwanie i czytanie ksiazek.

    Gdy sie nie powiedzie, zostaje oryginalne pytanie i zwykla odpowiedz -
    gorsze wyszukiwanie jest lepsze niz brak odpowiedzi."""
    zapis = "\n".join(
        f"{'Pytanie' if rola == 'user' else 'Odpowiedź'}: {tekst}"
        for rola, tekst in (historia or [])[-OKNO_HISTORII:]
    )
    zapis = (zapis + "\n" if zapis else "") + f"Polecenie: {pytanie}"

    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": _ZROZUM_PROMPT},
                {"role": "user", "content": zapis},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "zrozumienie", "schema": _SCHEMA_ZROZUM, "strict": True},
            },
        )
        wynik = json.loads(odpowiedz.choices[0].message.content)
    except Exception:
        # Bez modelu forme widac po slowach polecenia. Gorzej niz z modelem,
        # ale "napisz artykul" nie przepadnie.
        return {
            "pytanie": pytanie,
            "forma": forma_po_slowach(pytanie),
            "o_uprawie": True,
            "temat": "",
            "ile_slow": zadana_dlugosc(pytanie),
        }

    return {
        "pytanie": (wynik.get("pytanie") or "").strip() or pytanie,
        "forma": wynik.get("forma", "odpowiedz"),
        "o_uprawie": bool(wynik.get("o_uprawie", True)),
        "temat": (wynik.get("temat") or "").strip(),
        "ile_slow": zadana_dlugosc(pytanie),
    }


def zbierz_fakty_do_pytania(
    db,
    pytanie: str,
    source_ids: list[int] | None = None,
    na_ksiazke: int = NA_KSIAZKE,
    zagadnienia: list[str] | None = None,
) -> tuple[list[dict], dict, dict, dict]:
    """Fakty wypisane OSOBNO z kazdej ksiazki z zakresu.

    Kazda ksiazka jest przeszukiwana i czytana na wlasnych prawach, po czym
    fakty ida razem do wyboru. Wczesniej byl jeden wspolny ranking akapitow
    i to sie nie skalowalo: przy dwunastu zaznaczonych ksiazkach na kazda
    wypadal jeden akapit, a czesc nie dostawala nic, wiec ksiazka slabsza
    jezykowo nie miala jak dojsc do glosu. Liczba ksiazek nie moze zmieniac
    zasad."""
    # Szukamy osobno dla polecenia i dla kazdego zagadnienia z planu. Jedno
    # wyszukiwanie na cale "napisz artykul o uprawie w tunelu" daje akapity
    # o wszystkim po trochu; osobne zapytanie o "podlewanie w upaly" trafia
    # tam, gdzie ksiazka naprawde o tym pisze.
    zapytania = [pytanie] + [z for z in (zagadnienia or []) if z]
    per_ksiazka: dict[int, list[int]] = {}
    # Ktory akapit przyszedl z ktorego zagadnienia - stad wiadomo pozniej,
    # ktore zagadnienia maja pokrycie w ksiazkach.
    znalezione_dla: dict[str, set[int]] = {}
    for zapytanie in zapytania:
        for source_id, akapity in szukaj_w_kazdej_ksiazce(zapytanie, source_ids, na_ksiazke).items():
            znane = per_ksiazka.setdefault(source_id, [])
            znane.extend(a for a in akapity if a not in znane)
            znalezione_dla.setdefault(zapytanie, set()).update(akapity)
    if not per_ksiazka:
        return [], {}, {}, {}, {}

    # Sufit na ksiazke, zeby plan z siedmioma zagadnieniami nie wpychal do
    # jednego wywolania stu akapitow.
    per_ksiazka = {sid: akapity[: na_ksiazke * 3] for sid, akapity in per_ksiazka.items()}

    wszystkie = [cid for lista in per_ksiazka.values() for cid in lista]
    chunks = db.query(Chunk).filter(Chunk.id.in_(wszystkie)).all()
    by_id = {c.id: c for c in chunks}
    pages = {p.id: p for p in db.query(Page).filter(Page.id.in_([c.page_id for c in chunks])).all()}
    sources = {s.id: s for s in db.query(Source).filter(Source.id.in_({c.source_id for c in chunks})).all()}
    poprzednie = _poprzednie_akapity(db, chunks)

    def kontekst(chunk_ids: list[int]) -> list[dict]:
        return [
            {
                "chunk_id": chunk.id,
                "source": sources[chunk.source_id].title,
                "page": pages[chunk.page_id].number,
                # Poczatek poprzedniego akapitu - bez tego model nie wie, czego
                # dotyczy fragment. Akapit "Niedobor wapnia... Jak zapobiegac:
                # Podnies pH gleby do okolo 6,0" wyglada jak porada o odczynie
                # gleby, a jest zaleceniem przy suchej zgniliznie wierzcholkowej
                # - nagłowek rozdzialu siedzi w akapicie obok.
                "poprzedni_fragment": poprzednie.get(chunk.id),
                "text": chunk.text,
            }
            for chunk in (by_id[cid] for cid in chunk_ids if cid in by_id)
        ]

    def z_jednej_ksiazki(chunk_ids: list[int]) -> list[dict]:
        """Fakty z jednej ksiazki, z jedna powtorka i bez prawa wywrocenia reszty.

        Wywolanie potrafi wrocic puste, choc te same akapity wywolane jeszcze raz
        daja kilkanascie faktow. Wyszukiwanie jest powtarzalne co do akapitu,
        wiec to model czasem wybiera latwe wyjscie i oddaje pusta liste. Stad
        trzy podejscia; dopiero trzecie puste znaczy, ze ksiazka naprawde nic
        na ten temat nie mowi.

        Blad jednej ksiazki nie moze zabrac odpowiedzi z pozostalych."""
        akapity = kontekst(chunk_ids)
        for podejscie in (1, 2, 3):
            try:
                wynik = _zbierz_fakty(pytanie, akapity)
            except Exception:
                wynik = []
            if wynik:
                return wynik
        return []

    # Rownolegle, bo przy kilkunastu ksiazkach czekanie po kolei robi z tego
    # minuty. Kazde wywolanie dotyczy jednej ksiazki i jest male.
    fakty: list[dict] = []
    with ThreadPoolExecutor(max_workers=RAZEM_KSIAZEK) as pula:
        for wynik in pula.map(z_jednej_ksiazki, per_ksiazka.values()):
            fakty.extend(wynik)
    return fakty, by_id, pages, sources, znalezione_dla


# Ile ksiazek czytamy naraz. Wyzej nie ma sensu - to zapytania do modelu,
# nie obliczenia.
RAZEM_KSIAZEK = 6


# Ile faktow musi stac za zagadnieniem, zeby uznac je za pokryte. Prog sluzy
# juz tylko decyzji "doszukiwac czy nie" - model piszacy planu nie widzi, wiec
# fakty chudego tematu i tak trafiaja do wspolnej puli. Dwa fakty okazaly sie
# za malo: powstawal z nich akapit w rodzaju "Nawadnianie wymaga unikania
# nierownomiernego podlewania", czyli jedno chude zdanie udajace rozdzial.
MIN_FAKTOW_NA_ZAGADNIENIE = 4

# Ile zagadnien warto doszukiwac. Kazde to osobne wyszukiwanie i ponowne
# czytanie ksiazek - przy siedmiu brakach odpowiedz rosla do kilku minut.
MAX_DOSZUKIWAN = 3


def zagadnienia_z_pokryciem(
    zagadnienia: list[str], fakty: list[dict], znalezione_dla: dict[str, set[int]]
) -> list[str]:
    """Zagadnienia, o ktorych ksiazki naprawde cos mowia.

    Plan powstaje z wiedzy modelu, wiec planuje tez rozdzialy, ktorych zrodla
    nie maja. Powiedziane wprost w prompcie - i zignorowane: artykul o tunelach
    dostal trzy akapity w rodzaju "wybor odmian nie zostal omowiony w dostepnych
    faktach". Zamiast przekonywac model, nie dajemy mu tych zagadnien."""
    maja: list[str] = []
    for zagadnienie in zagadnienia:
        akapity = znalezione_dla.get(zagadnienie, set())
        ile = sum(1 for f in fakty if f.get("chunk_id") in akapity)
        if ile >= MIN_FAKTOW_NA_ZAGADNIENIE:
            maja.append(zagadnienie)
    return maja


def przytnij_fakty(fakty: list[dict], by_id: dict, ile: int) -> list[dict]:
    """Tyle faktow, ile zmiesci sie w tekscie - po rowno z kazdej ksiazki.

    Byl tu osobny krok: model ocenial kazdy fakt i wybieral najlepsze. Wypadl,
    bo niewiele wnosil, a wnosil wlasna awarie - z czterdziestu trzech faktow
    zostawial pietnascie przy limicie trzydziestu szesciu i artykul wychodzil
    pusty. Fakty sa juz zebrane pod to jedno pytanie i ustawione w kolejnosci
    trafnosci, wiec wystarczy ucinac.

    Bierzemy na zmiane po jednym z kazdej ksiazki, zeby przyciecie nie wycielo
    calej ksiazki - a o tym, ktore z nich wejda do zdania, decyduje juz model
    piszacy."""
    if len(fakty) <= ile:
        return fakty

    kolejki: dict[int, list[dict]] = {}
    for fakt in fakty:
        chunk = by_id.get(fakt.get("chunk_id"))
        kolejki.setdefault(chunk.source_id if chunk else 0, []).append(fakt)

    wynik: list[dict] = []
    while len(wynik) < ile and any(kolejki.values()):
        for kolejka in kolejki.values():
            if kolejka and len(wynik) < ile:
                wynik.append(kolejka.pop(0))
    return wynik


def answer_question(
    question: str,
    source_ids: list[int] | None = None,
    historia: list[tuple[str, str]] | None = None,
) -> dict:
    """Cztery etapy: zrozum, przeszukaj, napisz, sprawdz.

    Forma tekstu wychodzi z pierwszego etapu, nie z ustawien: klient nie
    zapowiada, czy chce odpowiedz na pytanie, artykul czy wpis na Facebooka.
    Program ma to obsluzyc tak samo, z jedyna przewaga - kazda liczba w tekscie
    ma pokrycie w ksiazce."""
    zrozumienie = zrozum_pytanie(historia or [], question)
    if not zrozumienie["o_uprawie"]:
        # Odsiane na wejsciu, przed wyszukiwaniem i czytaniem ksiazek. Inaczej
        # pytanie o pogode przechodzi cala droge i kosztuje kilkanascie wywolan,
        # zeby na koncu uslyszec to samo.
        return _nie_o_tym()

    pytanie = zrozumienie["pytanie"]
    nazwa_formy = zrozumienie["forma"]
    forma = FORMY.get(nazwa_formy, FORMY["odpowiedz"])

    # Plan tylko dla dluzszych tekstow. Na pytanie o odczyn gleby nie ma czego
    # planowac, a wywolanie kosztowaloby tyle samo co odpowiedz.
    zagadnienia = zaplanuj(pytanie, nazwa_formy) if forma["planuje"] else []

    db = SessionLocal()
    try:
        fakty, by_id, pages, sources, znalezione_dla = zbierz_fakty_do_pytania(
            db, pytanie, source_ids, na_ksiazke=forma["na_ksiazke"], zagadnienia=zagadnienia
        )
        if not fakty:
            return _no_data()

        maja_pokrycie = zagadnienia_z_pokryciem(zagadnienia, fakty, znalezione_dla)
        brakujace = [z for z in zagadnienia if z not in maja_pokrycie]
        if brakujace:
            # Druga runda: zagadnienie moze byc w ksiazce pod innym slowem
            # ("ogławianie" zamiast "obcinanie czubkow"). Dopiero gdy i to nie
            # trafi, zagadnienie wypada z planu.
            # Najwyzej trzy zagadnienia i wezszy zakres: druga runda to pelne
            # zbieranie faktow od nowa, wiec przy siedmiu brakach potrafila
            # wydluzyc odpowiedz z minuty do szesciu.
            inaczej = powiedz_inaczej(brakujace[:MAX_DOSZUKIWAN])
            dodatkowe = [f for lista in inaczej.values() for f in lista]
            if dodatkowe:
                wiecej, by_id2, pages2, sources2, znalezione2 = zbierz_fakty_do_pytania(
                    db, pytanie, source_ids, na_ksiazke=4, zagadnienia=dodatkowe
                )
                znane = {(f.get("chunk_id"), f.get("tresc")) for f in fakty}
                fakty.extend(f for f in wiecej if (f.get("chunk_id"), f.get("tresc")) not in znane)
                by_id.update(by_id2)
                pages.update(pages2)
                sources.update(sources2)
                # Trafienia z zamiennika licza sie na konto zagadnienia, ktore
                # zastapil - inaczej pokrycie nadal wyszloby zerowe.
                for zagadnienie, zamienniki in inaczej.items():
                    for zamiennik in zamienniki:
                        znalezione_dla.setdefault(zagadnienie, set()).update(
                            znalezione2.get(zamiennik, set())
                        )
                maja_pokrycie = zagadnienia_z_pokryciem(zagadnienia, fakty, znalezione_dla)
        zagadnienia = maja_pokrycie

        do_pisania = przytnij_fakty(fakty, by_id, forma["faktow"])
        jak = forma["jak"]
        if zrozumienie.get("ile_slow"):
            # Liczba z polecenia jest celem, nie nakazem - o gornej granicy i tak
            # decyduja fakty, a doklejanie waty do liczby juz raz tu bylo.
            jak += (
                f" Poproszono o około {zrozumienie['ile_slow']} słów — pisz w tę stronę,"
                " ale ani jednego zdania ponad to, co mówią fakty."
            )
        # Plan sluzy WYLACZNIE wyszukiwaniu. Model piszacy go nie widzi -
        # dostajac liste tematow, odhaczal je po kolei i kazdy akapit zaczynal
        # sie od nazwy zagadnienia: "Nawadnianie... wymaga", "Ochrona...
        # wymaga". Tekst wygladal jak wypelniony formularz.
        raw = _napisz_z_faktow(pytanie, do_pisania, ustalenia_dla(db, list(by_id)), jak)
        raw, usuniete = po_kontroli(raw, do_pisania)
        odpowiedz = _verify(raw, by_id, pages, sources)
        odpowiedz["usuniete"] = usuniete

        # Roznice miedzy ksiazkami szukamy PO zlozeniu odpowiedzi. To osobna
        # sprawa niz pisanie i nie ma prawa na nie wplywac - a fakty i tak sa
        # juz zebrane, wiec drugi raz ich nie kupujemy.
        znajdz_konflikty(db, pytanie, fakty, by_id)
        return odpowiedz
    finally:
        db.close()


def _poprzednie_akapity(db, chunks: list[Chunk]) -> dict[int, str | None]:
    """Poczatek akapitu poprzedzajacego kazdy ze znalezionych.

    Wystarczy kilkadziesiat znakow: chodzi o to, zeby model zobaczyl naglowek
    albo pierwsze zdanie sekcji i wiedzial, czego dotyczy fragment - nie o to,
    zeby dostal drugi raz cala strone."""
    wynik: dict[int, str | None] = {}
    for chunk in chunks:
        if chunk.seq == 0:
            wynik[chunk.id] = None
            continue
        poprzedni = (
            db.query(Chunk)
            .filter(Chunk.page_id == chunk.page_id, Chunk.seq < chunk.seq)
            .order_by(Chunk.seq.desc())
            .first()
        )
        wynik[chunk.id] = poprzedni.text[:200] if poprzedni else None
    return wynik


def _nie_o_tym() -> dict:
    """Pytanie spoza dziedziny ksiazek. Mowimy to wprost i nie szukamy."""
    return {
        "sentences": [],
        "sources": [],
        "note": "To pytanie nie dotyczy uprawy — nie znajdę tego w książkach ogrodniczych.",
    }


def _no_data() -> dict:
    """Brak pokrycia w zrodlach.

    Decyzja zapada PRZED wywolaniem modelu - nie polegamy na tym, ze sam powie
    "nie wiem". To jedyna rzecz, ktora odroznia ten program od zwyklego czatu."""
    return {
        "sentences": [],
        "sources": [],
        "note": "Nie mam tego w źródłach. Dodaj książkę albo wklej tekst na ten temat.",
    }


def _zbierz_fakty(question: str, context: list[dict]) -> list[dict]:
    """Krok pierwszy: co akapity mowia na temat pytania.

    Zbieramy surowe informacje, nie zdania. To jest sedno podzialu na dwa
    kroki: gdy model widzi zdania z ksiazki i ma na nie odpowiedziec, kopiuje
    ich rytm - a ksiazki sa pisane jezykiem urzedowym ("zalecanymi podlozami
    sa...", "nalezy rozpoczac..."). Probowalem to leczyc lista zakazanych slow
    w prompcie i poprawianiem gotowych zdan; model za kazdym razem znajdowal
    kolejny urzedowy zwrot, bo zrodlo ciagnelo go w te strone.

    Po rozdzieleniu krokow w drugim model nie widzi juz zdan ksiazki, tylko
    suche fakty - nie ma czego parafrazowac."""
    odpowiedz = _openai.chat.completions.create(
        model=settings.answer_model,
        temperature=0,
        messages=[
            {"role": "system", "content": ZBIERANIE_PROMPT},
            {
                "role": "user",
                "content": json.dumps({"pytanie": question, "akapity": context}, ensure_ascii=False),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "fakty", "schema": _SCHEMA_FAKTY, "strict": True},
        },
    )
    return json.loads(odpowiedz.choices[0].message.content).get("fakty", [])


def _napisz_z_faktow(
    question: str,
    fakty: list[dict],
    ustalenia: list[dict] | None = None,
    jak: str = "",
) -> dict:
    """Krok drugi: odpowiedz ulozona z faktow.

    Model dostaje tylko tresc i warunek - bez cytatow i bez zdan zrodlowych.
    Cytat wraca pozniej, przypisany przez numer faktu (_verify)."""
    do_napisania = [
        {"nr": i, "tresc": f.get("tresc", ""), "warunek": f.get("warunek", "")}
        for i, f in enumerate(fakty)
    ]
    odpowiedz = _openai.chat.completions.create(
        model=settings.answer_model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": PISANIE_PROMPT + "\n\n" + (jak or FORMY["odpowiedz"]["jak"])},
            {
                "role": "user",
                "content": json.dumps(
                    {"pytanie": question, "fakty": do_napisania, "ustalenia": ustalenia or []},
                    ensure_ascii=False,
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "odpowiedz", "schema": _SCHEMA_ODPOWIEDZ, "strict": True},
        },
    )
    napisane = json.loads(odpowiedz.choices[0].message.content).get("czesci", [])

    # Cytat wraca do kawalka przez numer faktu. Kawalek moze stac na kilku
    # faktach naraz - i o to chodzi: jednostka tekstu jest fragment zdania,
    # nie cale zdanie. Gdy jednostka bylo zdanie, model dostawal liste faktow
    # i pole na liste zdan, wiec pisal jeden fakt = jedno zdanie, a odpowiedz
    # wygladala jak wyliczanka, cokolwiek mowil prompt.
    czesci = []
    for czesc in napisane:
        numery = [n for n in czesc.get("fakty", []) if isinstance(n, int) and 0 <= n < len(fakty)]
        zrodla: list[dict] = []
        for numer in numery:
            fakt = fakty[numer]
            # Dwa fakty z tego samego akapitu to jeden przypis, nie dwa.
            if any(z["chunk_id"] == fakt.get("chunk_id") for z in zrodla):
                continue
            zrodla.append({"chunk_id": fakt.get("chunk_id"), "quote": fakt.get("quote", "")})
        # Kawalek z ustaleniem nie dostaje odnosnika do ksiazki: ksiazka mowi
        # co innego, wiec odnosnik do niej bylby nieprawda.
        uzyte = [
            (ustalenia or [])[n]["temat"]
            for n in czesc.get("ustalenia", [])
            if isinstance(n, int) and 0 <= n < len(ustalenia or [])
        ]
        czesci.append(
            {
                "text": czesc.get("tekst", ""),
                "zrodla": [] if uzyte else zrodla,
                "ustalenie": uzyte[0] if uzyte else None,
                "nowy_akapit": bool(czesc.get("nowy_akapit")),
                "fakty_nr": numery,
            }
        )
    return {"czesci": czesci}


# Slowa, z ktorych wolno zlozyc kawalek bez przypisu. Kawalek bez pokrycia
# w ksiazce ma prawo istniec tylko jako spoiwo miedzy dwoma, ktore pokrycie
# maja - inaczej wymuszalibysmy, zeby kazdy kawalek byl samodzielna porcja
# faktu, a wtedy model tnie wylacznie na granicy zdania i odpowiedz znowu
# wyglada jak wyliczanka. Lista jest zamknieta celowo: przez te furtke nie ma
# wejsc zadna tresc, wiec nie ma tu ani jednego slowa nazywajacego rzecz.
_SPOIWO = {
    "a", "i", "oraz", "ale", "lecz", "za", "to", "natomiast", "zaś", "zas",
    "choć", "choc", "chociaż", "chociaz", "bo", "więc", "wiec", "też", "tez",
    "także", "takze", "czyli", "jednak", "tylko", "nie", "przy", "tym",
}


# Zwroty, ktorymi wolno polaczyc dwa fakty w osobne zdanie. Lista zamknieta
# z tego samego powodu co _SPOIWO: zdanie laczace nie moze niczego twierdzic,
# a najprosciej to zagwarantowac, wybierajac z gotowego zestawu. Bez nich
# odpowiedz jest zbitka faktow jeden po drugim i nikt tego nie czyta.
_LACZNIKI = {
    "do tego", "na koniec", "jeszcze jedno", "przy okazji", "za to",
    "i jeszcze", "poza tym warto wiedziec tyle", "tyle o tym",
}


def jest_spoiwem(tekst: str) -> bool:
    """Czy kawalek bez przypisu jest samym spoiwem, bez wlasnej tresci."""
    slowa = re.findall(r"\w+", tekst.lower(), flags=re.UNICODE)
    if not slowa:
        return True
    if " ".join(slowa) in {normalize(l) for l in _LACZNIKI}:
        return True
    return all(slowo in _SPOIWO for slowo in slowa)


# Przed tymi znakami nie stawiamy spacji przy sklejaniu kawalkow.
BEZ_SPACJI = ',.;:!?…)»"\''


_KONIEC_ZDANIA = re.compile(r"[.!?…]")


def _na_zdania(czesci: list[dict], fakty: list[dict]) -> list[dict]:
    """Kawalki pogrupowane w zdania - kontrola ocenia zdania, nie kawalki.

    Kawalek to czesc zdania, wiec ocena "czy to twierdzenie wynika z faktow"
    na kawalku bylaby oceną urwanego fragmentu."""
    zdania: list[dict] = []
    biezace: dict | None = None
    for numer, czesc in enumerate(czesci):
        if biezace is None:
            biezace = {
                "nr": len(zdania),
                "tekst": "",
                "fakty": [],
                "indeksy": [],
                "nowy_akapit": bool(czesc.get("nowy_akapit")),
            }
        biezace["tekst"] += czesc.get("text", "")
        biezace["indeksy"].append(numer)
        for nr_faktu in czesc.get("fakty_nr", []):
            tresc = fakty[nr_faktu].get("tresc", "") if 0 <= nr_faktu < len(fakty) else ""
            if tresc and tresc not in biezace["fakty"]:
                biezace["fakty"].append(tresc)
        if _KONIEC_ZDANIA.search(czesc.get("text", "")):
            zdania.append(biezace)
            biezace = None
    if biezace is not None and biezace["tekst"].strip():
        zdania.append(biezace)
    return zdania


def _fakty_akapitu(zdania: list[dict], numer: int) -> list[str]:
    """Fakty wszystkich zdan tego akapitu - warunek moze stac w ktorymkolwiek."""
    poczatek = numer
    while poczatek > 0 and not zdania[poczatek]["nowy_akapit"]:
        poczatek -= 1
    koniec = numer + 1
    while koniec < len(zdania) and not zdania[koniec]["nowy_akapit"]:
        koniec += 1
    wszystkie: list[str] = []
    for zdanie in zdania[poczatek:koniec]:
        wszystkie.extend(f for f in zdanie["fakty"] if f not in wszystkie)
    return wszystkie


def po_kontroli(raw: dict, fakty: list[dict]) -> tuple[dict, list[str]]:
    """Usuwa zdania, ktore twierdza cos spoza faktow. Zwraca tekst i to, co wypadlo.

    Zdanie, ktore niczego nie twierdzi, zostaje bez przypisu - to jest cala
    zmiana: dzieki niej tekst moze miec przejscia i wprowadzenia, zamiast byc
    lista faktow.

    To ocena modelu i moze sie mylic, wiec nie zastepuje sprawdzenia cytatu,
    tylko dokłada sie nad nim."""
    czesci = raw.get("czesci", [])
    zdania = _na_zdania(czesci, fakty)
    # Zdanie oceniane samotnie wyglada na pozbawione warunku, gdy warunek stoi
    # zdanie wyzej: "W takich warunkach podlewaj rzadziej". Dlatego kontrola
    # dostaje zdanie poprzedzajace i fakty calego akapitu.
    oceny = sprawdz_zdania(
        [
            {
                "nr": z["nr"],
                "tekst": z["tekst"],
                "fakty": z["fakty"],
                "poprzednie": zdania[numer - 1]["tekst"] if numer else "",
                "fakty_akapitu": _fakty_akapitu(zdania, numer),
            }
            for numer, z in enumerate(zdania)
        ]
    )
    if not oceny:
        return raw, []

    # Zdanie bez pokrycia dostaje najpierw szanse na skrocenie do tego, co
    # naprawde stoi w faktach. Dopiero gdy nic sensownego nie zostaje, wypada.
    do_poprawy = [
        {"nr": z["nr"], "tekst": z["tekst"].strip(), "fakty": z["fakty"]}
        for z in zdania
        if oceny.get(z["nr"]) and do_usuniecia(oceny[z["nr"]])
    ]
    poprawione = popraw_lub_skresl(do_poprawy) if do_poprawy else {}

    wyrzucone: set[int] = set()
    powody: list[str] = []
    for zdanie in zdania:
        ocena = oceny.get(zdanie["nr"])
        if ocena is None:
            continue
        if do_usuniecia(ocena):
            nowy = poprawione.get(zdanie["nr"], "")
            if nowy:
                # Skrocone zdanie wchodzi w pierwszy kawalek, reszta znika -
                # a zrodla calego zdania zbieramy w tym kawalku, zeby przypis
                # nie przepadl razem z reszta.
                pierwszy = zdanie["indeksy"][0]
                czesci[pierwszy]["text"] = (" " if zdanie["tekst"][:1].isspace() else "") + nowy
                for indeks in zdanie["indeksy"][1:]:
                    for zrodlo in czesci[indeks].get("zrodla", []):
                        if zrodlo not in czesci[pierwszy].setdefault("zrodla", []):
                            czesci[pierwszy]["zrodla"].append(zrodlo)
                    wyrzucone.add(indeks)
                continue
            wyrzucone.update(zdanie["indeksy"])
            powody.append(zdanie["tekst"].strip())
        elif do_oznaczenia(ocena):
            for indeks in zdanie["indeksy"]:
                czesci[indeks]["bez_warunku"] = ocena.get("co_nie_pasuje", "")
        elif not ocena.get("twierdzi"):
            # Zdanie przejsciowe - nie potrzebuje przypisu i nie ma byc
            # oznaczone jako niepotwierdzone.
            for indeks in zdanie["indeksy"]:
                czesci[indeks]["przejscie"] = True

    zostale = [c for numer, c in enumerate(czesci) if numer not in wyrzucone]

    # Po usunieciu zostaja szwy: "Dlatego..." bez tego, co bylo przedtem.
    # Naprawa moze tylko skracac, wiec nie wprowadzi nowej tresci - dlatego
    # poprawionych zdan nie trzeba sprawdzac drugi raz.
    if powody and zostale:
        for numer, nowy in zszyj(zostale, powody).items():
            zostale[numer]["text"] = nowy
        zostale = [c for c in zostale if c.get("text", "").strip() or c.get("zrodla")]

    raw["czesci"] = zostale
    return raw, powody


def _verify(raw: dict, by_id: dict, pages: dict, sources: dict) -> dict:
    """Sprawdza kazdy cytat i sklada odpowiedz do pokazania."""
    czesci = []
    used_chunks: list[int] = []

    for item in raw.get("czesci", []):
        zrodla = []
        for wskazanie in item.get("zrodla", []):
            chunk = by_id.get(wskazanie.get("chunk_id"))
            if chunk is None:
                # Model wskazal akapit, ktorego mu nie dalismy.
                continue
            if chunk.id not in used_chunks:
                used_chunks.append(chunk.id)
            page = pages[chunk.page_id]
            source = sources[chunk.source_id]
            zrodla.append(
                {
                    "chunk_id": chunk.id,
                    "source_id": source.id,
                    "source_title": source.title,
                    "source_kind": source.kind,
                    "page": page.number,
                    # Cytat z odczytu obrazu jest mniej pewny niz z warstwy
                    # tekstowej: na pomiarach 94-98% slow sie zgadza, a polskie
                    # znaki potrafia sie przekrecic ("lodyga" na "todyga").
                    "z_obrazu": bool(getattr(page, "z_obrazu", False)),
                    "quote": wskazanie.get("quote", ""),
                    "verified": quote_is_in_chunk(wskazanie.get("quote", ""), chunk.text),
                    "marker": used_chunks.index(chunk.id) + 1,
                }
            )

        tekst = _brakujaca_spacja(item.get("text", ""))
        ustalenie = item.get("ustalenie")
        spoiwo = not zrodla and not ustalenie and (item.get("przejscie") or jest_spoiwem(tekst))
        czesci.append(
            {
                "text": tekst,
                # Samo spoiwo niczego nie twierdzi, wiec nie ma w nim czego
                # sprawdzac. Kawalek bez przypisu, ktory JEDNAK cos mowi,
                # traktujemy tak samo jak zmyslony cytat.
                # Ustalenie rozstrzygnal czlowiek - to mocniejsze niz cytat.
                "verified": bool(ustalenie) or spoiwo or (bool(zrodla) and all(z["verified"] for z in zrodla)),
                "ustalenie": ustalenie,
                "nowy_akapit": bool(item.get("nowy_akapit")),
                "spoiwo": spoiwo,
                "sources": zrodla,
            }
        )

    if not czesci:
        return _no_data()

    source_list = []
    for index, chunk_id in enumerate(used_chunks, start=1):
        chunk = by_id[chunk_id]
        source_list.append(
            {
                "marker": index,
                "chunk_id": chunk_id,
                "source_id": chunk.source_id,
                "source_title": sources[chunk.source_id].title,
                "source_kind": sources[chunk.source_id].kind,
                "page": pages[chunk.page_id].number,
                "z_obrazu": bool(getattr(pages[chunk.page_id], "z_obrazu", False)),
                "text": chunk.text,
            }
        )

    return {"sentences": czesci, "sources": source_list, "note": None}


# Kropka miedzy mala a wielka litera bez spacji - literowka modelu w srodku
# kawalka ("agrowloknina.Nie ma potrzeby"). Sklejanie kawalkow tego nie zlapie,
# bo to jeden kawalek.
_SKLEJONE_ZDANIA = re.compile(r"(?<=[a-ząćęłńóśźż])\.(?=[A-ZĄĆĘŁŃÓŚŹŻ])")


def _brakujaca_spacja(tekst: str) -> str:
    return _SKLEJONE_ZDANIA.sub(". ", tekst)


def sklej(czesci: list[dict]) -> str:
    """Kawalki sklejone w jeden tekst - z brakujaca spacja tam, gdzie trzeba.

    Model ma zaczynac kawalek od spacji, jesli stoi w srodku zdania. Czasem
    o tym zapomina, a sklejone bez spacji slowa wygladaja na blad programu."""
    tekst = ""
    for czesc in czesci:
        # Spacja na koncu kawalka odkleilaby przypis od slowa, przy ktorym stoi,
        # i przykleila go do nastepnego zdania: "owoców. ¹Podczas upalow".
        kawalek = czesc.get("text", "").rstrip()
        if tekst and kawalek and not kawalek[0].isspace() and kawalek[0] not in BEZ_SPACJI and not tekst.endswith(" "):
            kawalek = " " + kawalek
        tekst += kawalek
    return tekst

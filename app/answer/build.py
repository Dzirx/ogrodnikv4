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
- Jeśli żaden akapit nie odpowiada na pytanie, zwróć pustą listę."""


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

JAK ODDAJESZ ODPOWIEDŹ
Piszesz JEDEN płynny akapit. Oddajesz go pocięty na kawałki, ale to nadal jeden ciąg
tekstu — sklejone kawałki muszą się czytać jak zwykła wypowiedź.

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

Kawałek bez numerów też jest dozwolony, ale WYŁĄCZNIE jako spoiwo: przecinek, myślnik,
spójnik. ", a", " — ", ". Za to". W spoiwie nie wolno podać żadnej liczby ani nazwać
żadnej rzeczy — pierwsze słowo niosące treść musi stać w kawałku z numerem.

Wolno Ci też wpleść krótki zwrot łączący, wyłącznie jeden z tych: "Do tego", "Na koniec",
"Jeszcze jedno", "Przy okazji", "Za to". Żadnego innego — zwrot, którego tu nie ma,
zostanie odrzucony jako zdanie bez pokrycia w książce.

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
Długość dostajesz osobno, na końcu tych zasad. Ale ona jest granicą, nie zadaniem do
wykonania: jeśli faktów nie starcza na tyle tekstu, o ile poproszono, piszesz tyle, ile
masz z faktów, i kończysz.

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

_PRZEPISZ_PROMPT = """Przepisz ostatnie pytanie tak, żeby było zrozumiałe bez historii rozmowy,
i oceń, ile treści oczekuje pytający.

Przepisanie:
- Zwróć samo przepisane pytanie, bez komentarza.
- Uzupełnij brakujący podmiot z historii: "a jak w tunelu?" po pytaniu o wysiew pomidora
  to "wysiew pomidora w tunelu".
- Pytanie zaczynające się od "a", "no a", "to jak" albo samo dopowiadające warunek
  ("a w gruncie?", "a zimą?") ZAWSZE dotyczy poprzedniego tematu. Wstaw ten temat,
  nawet jeśli pytanie wygląda na zrozumiałe samo z siebie - dla wyszukiwania nie jest.
- Gdy pytanie prosi o więcej na temat, o którym już była mowa ("rozpisz to", "potrzebuję
  więcej szczegółów"), przepisane pytanie MUSI zachować tamten temat. To jest pogłębienie
  poprzedniej odpowiedzi, nie nowe pytanie.
- Nie dodawaj treści, której w rozmowie nie ma. Nie odpowiadaj na pytanie.

Głębokość:
- "krotka" — pytanie o konkret: "w jakim pH sadzić pomidory", "kiedy wysiewać rozsadę".
- "wiecej" — prośba o rozwinięcie: "rozpisz to", "potrzebuję więcej szczegółów",
  "a co jeszcze", "opisz dokładniej".
- "material" — prośba o tekst do czytania, nie o odpowiedź: "napisz artykuł",
  "przygotuj materiał", "zrób poradnik", "opisz szeroko temat"."""

_SCHEMA_PYTANIE = {
    "type": "object",
    "properties": {
        "pytanie": {"type": "string"},
        "glebokosc": {"type": "string", "enum": ["krotka", "wiecej", "material"]},
    },
    "required": ["pytanie", "glebokosc"],
    "additionalProperties": False,
}

# Ile akapitow z kazdej ksiazki i ile faktow do pisania - zaleznie od tego,
# o co poproszono. Do tej pory obie liczby byly stale, a prompt konczyl sie
# zdaniem "odpowiadaj krotko": prosba o artykul i prosba o wiecej szczegolow
# nie mialy jak niczego zmienic.
GLEBOKOSC = {
    "krotka": {"na_ksiazke": 6, "faktow": 12},
    "wiecej": {"na_ksiazke": 10, "faktow": 22},
    "material": {"na_ksiazke": 14, "faktow": 36},
}

_DLUGOSC = {
    "krotka": "Odpowiadaj krótko. Kilka zdań wystarczy. Jeden akapit.",
    "wiecej": (
        "Rozwiń temat: jeden albo dwa akapity po cztery, pięć zdań. Nowy akapit zaczynasz,"
        " gdy przechodzisz do innej rzeczy."
    ),
    "material": (
        "To ma być materiał do czytania, nie odpowiedź na pytanie. Cztery do sześciu akapitów,"
        " każdy po cztery, pięć zdań, każdy o czym innym — przygotowanie, termin, prowadzenie,"
        " kłopoty. Nie streszczaj na końcu i nie zapowiadaj na początku, po prostu pisz."
        " Masz na to kilkadziesiąt faktów: jeden akapit to kilka z nich, a nie jeden"
        " rozciągnięty na pięć zdań."
    ),
}


def zrozum_pytanie(historia: list[tuple[str, str]], pytanie: str) -> tuple[str, str]:
    """Pytanie zrozumiale bez historii rozmowy i oczekiwana glebokosc odpowiedzi.

    Bez przepisania "a w tunelu?" nie ma czego szukac - wyszukiwanie dostaje trzy
    slowa bez podmiotu. Bez glebokosci kazda odpowiedz wychodzila tak samo dluga,
    a "potrzebuje wiecej szczegolow" dawalo MNIEJ niz poprzednia: pytanie szlo
    do wyszukiwania jako nowe i trafialo gorzej.

    To krok WYSZUKIWANIA, nie redagowania: nie dotyka zasady, ze tresc odpowiedzi
    pochodzi wylacznie ze zrodel. Gdy sie nie powiedzie, zostaje oryginalne
    pytanie i krotka odpowiedz."""
    if not historia:
        zapis = f"Pytanie: {pytanie}"
    else:
        zapis = "\n".join(
            f"{'Pytanie' if rola == 'user' else 'Odpowiedź'}: {tekst}"
            for rola, tekst in historia[-OKNO_HISTORII:]
        ) + f"\nPytanie: {pytanie}"

    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": _PRZEPISZ_PROMPT},
                {"role": "user", "content": zapis},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "pytanie", "schema": _SCHEMA_PYTANIE, "strict": True},
            },
        )
        wynik = json.loads(odpowiedz.choices[0].message.content)
    except Exception:
        return pytanie, "krotka"

    return (wynik.get("pytanie") or "").strip() or pytanie, wynik.get("glebokosc", "krotka")


def zbierz_fakty_do_pytania(
    db, pytanie: str, source_ids: list[int] | None = None, na_ksiazke: int = NA_KSIAZKE
) -> tuple[list[dict], dict, dict, dict]:
    """Fakty wypisane OSOBNO z kazdej ksiazki z zakresu.

    Kazda ksiazka jest przeszukiwana i czytana na wlasnych prawach, po czym
    fakty ida razem do wyboru. Wczesniej byl jeden wspolny ranking akapitow
    i to sie nie skalowalo: przy dwunastu zaznaczonych ksiazkach na kazda
    wypadal jeden akapit, a czesc nie dostawala nic, wiec ksiazka slabsza
    jezykowo nie miala jak dojsc do glosu. Liczba ksiazek nie moze zmieniac
    zasad."""
    per_ksiazka = szukaj_w_kazdej_ksiazce(pytanie, source_ids, na_ksiazke)
    if not per_ksiazka:
        return [], {}, {}, {}

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

    # Rownolegle, bo przy kilkunastu ksiazkach czekanie po kolei robi z tego
    # minuty. Kazde wywolanie dotyczy jednej ksiazki i jest male.
    fakty: list[dict] = []
    with ThreadPoolExecutor(max_workers=RAZEM_KSIAZEK) as pula:
        for wynik in pula.map(lambda ids: _zbierz_fakty(pytanie, kontekst(ids)), per_ksiazka.values()):
            fakty.extend(wynik)
    return fakty, by_id, pages, sources


# Ile ksiazek czytamy naraz. Wyzej nie ma sensu - to zapytania do modelu,
# nie obliczenia.
RAZEM_KSIAZEK = 6

# Domyslna liczba faktow do pisania. Przy prosbie o material rosnie - patrz
# GLEBOKOSC.
MAX_FAKTOW = 12

SEDZIA_PROMPT = """Dostajesz pytanie i fakty wypisane z kilku książek ogrodniczych.
Wybierz te, z których należy napisać odpowiedź.

Zostawiasz fakt, gdy wprost odpowiada na zadane pytanie.

Odrzucasz fakt, gdy:
- mówi o czymś innym niż pytanie, choćby był z tej samej dziedziny,
- powtarza to, co inny wybrany fakt już mówi tymi samymi słowami.

Czego NIE WOLNO Ci odrzucić:
- faktu, który podaje INNĄ wartość niż fakt już wybrany. Dwie książki mogą się różnić
  i to jest informacja, nie usterka. Zostaw oba.
- faktu, który dotyczy innych warunków uprawy niż pozostałe. To nie powtórzenie.

Nie oszczędzaj. Zostaw WSZYSTKIE fakty dotyczące pytania, aż do liczby "ile_najwyzej" -
o długości tekstu decyduje kto inny, Ty tylko odsiewasz to, co jest o czymś innym. Odrzucenie
faktu, który pasuje do pytania, jest gorsze niż zostawienie jednego za dużo.

Zwróć numery wybranych faktów, najważniejsze najpierw."""

_SCHEMA_SEDZIA = {
    "type": "object",
    "properties": {"wybrane": {"type": "array", "items": {"type": "integer"}}},
    "required": ["wybrane"],
    "additionalProperties": False,
}


def wybierz_fakty(
    pytanie: str, fakty: list[dict], sources: dict, by_id: dict, ile: int = MAX_FAKTOW
) -> list[dict]:
    """Ktore z zebranych faktow ida do odpowiedzi.

    Krok osobny od zbierania, bo zbieranie ma byc szerokie, a odpowiedz krotka.
    Wczesniej robil to limit akapitow w wyszukiwaniu i dlatego jedno psulo
    drugie: zawezenie pod krotka odpowiedz odbieralo glos ksiazkom."""
    if len(fakty) <= ile:
        return fakty

    do_oceny = [
        {
            "nr": numer,
            "tresc": fakt.get("tresc", ""),
            "warunek": fakt.get("warunek", ""),
            "ksiazka": sources[by_id[fakt["chunk_id"]].source_id].title
            if fakt.get("chunk_id") in by_id
            else "",
        }
        for numer, fakt in enumerate(fakty)
    ]
    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SEDZIA_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"pytanie": pytanie, "ile_najwyzej": ile, "fakty": do_oceny},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "wybor", "schema": _SCHEMA_SEDZIA, "strict": True},
            },
        )
        wybrane = json.loads(odpowiedz.choices[0].message.content).get("wybrane", [])
    except Exception:
        # Gdy sedzia nie odpowie, bierzemy poczatek listy - gorsza odpowiedz
        # jest lepsza niz brak odpowiedzi.
        return fakty[:ile]

    numery = [n for n in wybrane if isinstance(n, int) and 0 <= n < len(fakty)]
    return [fakty[n] for n in dict.fromkeys(numery)][:ile] or fakty[:ile]


def answer_question(
    question: str,
    source_ids: list[int] | None = None,
    historia: list[tuple[str, str]] | None = None,
) -> dict:
    """Zwraca odpowiedz gotowa do pokazania: kawalki tekstu z cytatami i zrodla."""
    do_wyszukania, glebokosc = zrozum_pytanie(historia or [], question)
    miara = GLEBOKOSC.get(glebokosc, GLEBOKOSC["krotka"])

    db = SessionLocal()
    try:
        fakty, by_id, pages, sources = zbierz_fakty_do_pytania(
            db, do_wyszukania, source_ids, na_ksiazke=miara["na_ksiazke"]
        )
        if not fakty:
            return _no_data()

        # Roznic szukamy wsrod WSZYSTKICH zebranych faktow, nie tylko tych,
        # ktore wejda do odpowiedzi. Odpowiedz ma byc krotka, porownanie ksiazek
        # ma byc szerokie - to dwa rozne cele i nie moga dzielic jednej liczby.
        znajdz_konflikty(db, do_wyszukania, fakty, by_id)

        do_pisania = wybierz_fakty(do_wyszukania, fakty, sources, by_id, miara["faktow"])
        raw = _napisz_z_faktow(
            do_wyszukania, do_pisania, ustalenia_dla(db, list(by_id)), glebokosc
        )
        return _verify(raw, by_id, pages, sources)
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
    question: str, fakty: list[dict], ustalenia: list[dict] | None = None, glebokosc: str = "krotka"
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
            {"role": "system", "content": PISANIE_PROMPT + "\n\n" + _DLUGOSC.get(glebokosc, _DLUGOSC["krotka"])},
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
                    "quote": wskazanie.get("quote", ""),
                    "verified": quote_is_in_chunk(wskazanie.get("quote", ""), chunk.text),
                    "marker": used_chunks.index(chunk.id) + 1,
                }
            )

        tekst = item.get("text", "")
        ustalenie = item.get("ustalenie")
        spoiwo = not zrodla and not ustalenie and jest_spoiwem(tekst)
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
                "text": chunk.text,
            }
        )

    return {"sentences": czesci, "sources": source_list, "note": None}


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

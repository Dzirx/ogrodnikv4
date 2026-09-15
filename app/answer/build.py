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

from openai import OpenAI

from app.answer.cytaty import normalize, quote_is_in_chunk
from app.answer.konflikty import ustalenia_dla, znajdz_konflikty  # noqa: F401  (czytane też z tego modułu)
from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Chunk, Page, Source
from app.search.index import search

_openai = OpenAI(api_key=settings.openai_api_key)

ZBIERANIE_PROMPT = """Wypisz fakty, które podane akapity mówią na temat pytania.

To pierwszy z dwóch kroków: teraz tylko zbierasz surowe informacje, nie piszesz odpowiedzi.

Dla każdego faktu podaj:
- "tresc": sama informacja, możliwie zwięźle. Nie zdanie z książki, tylko to, co ono mówi. Zamiast "Zalecanymi podłożami do siewu są tzw. ziemie inspektowe lub substrat z torfu wysokiego, który jest odkwaszony i ma odczyn pH 6,0–6,5" napisz "podłoże do siewu: pH 6,0–6,5, odkwaszony torf wysoki albo ziemia inspektowa".
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
- Nie zaczynaj dwóch zdań tym samym słowem. Ani razu w całej odpowiedzi. Jeśli trzy zdania
  z rzędu zaczynają się od tego samego czasownika, układasz listę — połącz je w jedno.
- Nie więcej niż pięć zdań. Jeśli faktów jest więcej, wybierz te, które wprost odpowiadają
  na pytanie, i zostaw resztę.
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

Kawałek, który cokolwiek mówi, podaje numery faktów, na których stoi. Jeśli następny
kawałek nadal stoi na tym samym fakcie, powtórz ten numer.

Kawałek bez numerów też jest dozwolony, ale WYŁĄCZNIE jako spoiwo: przecinek, myślnik,
spójnik. ", a", " — ", ". Za to". Nic więcej. W spoiwie nie wolno podać żadnej liczby
ani nazwać żadnej rzeczy — pierwsze słowo niosące treść musi stać w kawałku z numerem.

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

GRANICA SWOBODY — to najważniejsze
Wolno Ci zmienić SPOSÓB powiedzenia. Nie wolno dodać ani jednej informacji, której nie ma
w faktach.

Najczęstsza pokusa to dopisanie uzasadnienia. Jeśli fakt mówi "podlewać pod krzew, nie moczyć
liści", to napisz właśnie tyle — nie dodawaj "bo moczenie liści sprzyja chorobom", nawet jeśli
to prawda. Tak samo "rób to rano albo wieczorem" zostaje bez "żeby woda nie parowała".

Źle:    "Lej pod krzew, nie na liście, bo to może zaszkodzić roślinom."
Dobrze: "Lej pod krzew, nie na liście."

Żadnych "bo", "żeby", "dzięki czemu", "co pozwala" — chyba że ten powód stoi wprost w fakcie.

Odpowiadaj krótko. Kilka zdań wystarczy."""


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
                },
                "required": ["tekst", "fakty", "ustalenia"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["czesci"],
    "additionalProperties": False,
}

# Ile ostatnich wiadomosci wystarczy, zeby zrozumiec pytanie doprecyzowujace.
OKNO_HISTORII = 4

_PRZEPISZ_PROMPT = """Przepisz ostatnie pytanie tak, żeby było zrozumiałe bez historii rozmowy.

Zasady:
- Zwróć samo przepisane pytanie, bez komentarza.
- Uzupełnij brakujący podmiot z historii: "a w tunelu?" po pytaniu o wysiew pomidora to "wysiew pomidora w tunelu".
- Nie dodawaj treści, której w rozmowie nie ma. Nie odpowiadaj na pytanie.
- Jeśli pytanie jest już samodzielne, zwróć je bez zmian."""


def przepisz_pytanie(historia: list[tuple[str, str]], pytanie: str) -> str:
    """Pytanie zrozumiale bez historii rozmowy.

    Bez tego "a w tunelu?" nie ma czego szukac - wyszukiwanie dostaje trzy
    slowa bez podmiotu i zwraca przypadkowe akapity.

    To krok WYSZUKIWANIA, nie redagowania: przepisanie nie dotyka zasady, ze
    tresc odpowiedzi pochodzi wylacznie ze zrodel. Gdy sie nie powiedzie,
    zostaje oryginalne pytanie - gorsze wyszukiwanie jest lepsze niz brak
    odpowiedzi."""
    if not historia:
        return pytanie

    zapis = "\n".join(
        f"{'Pytanie' if rola == 'user' else 'Odpowiedź'}: {tekst}"
        for rola, tekst in historia[-OKNO_HISTORII:]
    )
    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": _PRZEPISZ_PROMPT},
                {"role": "user", "content": f"{zapis}\nPytanie: {pytanie}"},
            ],
        )
        return (odpowiedz.choices[0].message.content or "").strip() or pytanie
    except Exception:
        return pytanie


def zbierz_fakty_do_pytania(
    db, pytanie: str, source_ids: list[int] | None = None
) -> tuple[list[dict], dict, dict, dict]:
    """Wyszukanie akapitow i wypisanie z nich faktow.

    Wspolny poczatek dwoch drog: odpowiadania na pytanie redaktora i przegladu
    nowej ksiazki. Przeglad musi isc dokladnie ta sama sciezka, bo inaczej
    roznice znalezione automatycznie rzadzilyby sie innymi regulami niz te
    znalezione przy rozmowie."""
    chunk_ids = search(pytanie, source_ids=source_ids)
    if not chunk_ids:
        return [], {}, {}, {}

    chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
    by_id = {c.id: c for c in chunks}
    pages = {p.id: p for p in db.query(Page).filter(Page.id.in_([c.page_id for c in chunks])).all()}
    sources = {s.id: s for s in db.query(Source).filter(Source.id.in_({c.source_id for c in chunks})).all()}

    poprzednie = _poprzednie_akapity(db, [by_id[cid] for cid in chunk_ids if cid in by_id])
    context = [
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
        # Kolejnosc z wyszukiwania - najtrafniejsze najpierw.
        for chunk in (by_id[cid] for cid in chunk_ids if cid in by_id)
    ]
    return _zbierz_fakty(pytanie, context), by_id, pages, sources


def answer_question(
    question: str,
    source_ids: list[int] | None = None,
    historia: list[tuple[str, str]] | None = None,
) -> dict:
    """Zwraca odpowiedz gotowa do pokazania: kawalki tekstu z cytatami i zrodla."""
    do_wyszukania = przepisz_pytanie(historia or [], question)

    db = SessionLocal()
    try:
        fakty, by_id, pages, sources = zbierz_fakty_do_pytania(db, do_wyszukania, source_ids)
        if not fakty:
            return _no_data()

        # Roznice miedzy ksiazkami wychodza na jaw wlasnie tutaj: fakty sa juz
        # zebrane dla jednego pytania, wiec z definicji dotycza tej samej rzeczy.
        znajdz_konflikty(db, do_wyszukania, fakty, by_id)

        raw = _napisz_z_faktow(do_wyszukania, fakty, ustalenia_dla(db, list(by_id)))
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


def _napisz_z_faktow(question: str, fakty: list[dict], ustalenia: list[dict] | None = None) -> dict:
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
            {"role": "system", "content": PISANIE_PROMPT},
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
            {"text": czesc.get("tekst", ""), "zrodla": [] if uzyte else zrodla, "ustalenie": uzyte[0] if uzyte else None}
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


def jest_spoiwem(tekst: str) -> bool:
    """Czy kawalek bez przypisu jest samym spoiwem, bez wlasnej tresci."""
    slowa = re.findall(r"\w+", tekst.lower(), flags=re.UNICODE)
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

"""Pytanie -> odpowiedz zlozona ze zdan, z ktorych kazde wskazuje swoj akapit.

Podzial pracy, odwrotnie niz w pierwszej wersji:

MODEL pisze odpowiedz i przy kazdym zdaniu podaje, z ktorego akapitu je wzial
i ktory fragment to potwierdza. Nie ma slotow podstawianych do tekstu - model
pisze liczby wprost, bo cytat i tak zostanie sprawdzony.

KOD sprawdza jedna rzecz: czy podany cytat naprawde wystepuje w tym akapicie.
Jedno porownanie tekstu, zero kosztu, pewnosc ktorej model nie da. Zdanie,
ktore tego nie przechodzi, zostaje w odpowiedzi, ale jest widocznie oznaczone -
tak jak reszta systemu traktuje rzeczy niepewne, zamiast je po cichu ukrywac.
"""

import json
import re

from openai import OpenAI

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import Chunk, Page, Source
from app.answer.styl import sprawdz, sprawdz_odpowiedz
from app.search.index import search

_openai = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """Odpowiadasz na pytania o ogrodnictwo wyłącznie na podstawie podanych akapitów ze źródeł.

Pisz po polsku, z pełnymi znakami diakrytycznymi: ą ć ę ł ń ó ś ź ż. Nigdy nie pomijaj ogonków.

Zasady treści:
- Każde zdanie odpowiedzi musi pochodzić z konkretnego akapitu. Podajesz jego "chunk_id" oraz "quote" — dosłowny fragment tego akapitu.
- "quote" musi POTWIERDZAĆ to, co napisałeś w "text". Nie wystarczy, że pochodzi z tego samego akapitu i dotyczy podobnego tematu. Jeśli akapit mówi, że niedobór wapnia przy niskim pH powoduje chorobę, to NIE jest potwierdzenie zdania "pomidor lubi glebę lekko kwaśną" — to zupełnie inna informacja.
- "quote" przepisz znak w znak z akapitu. Nie poprawiaj go, nie skracaj w środku, nie zmieniaj interpunkcji.
- Nie pisz niczego, czego nie ma w akapitach. Zero własnej wiedzy o ogrodnictwie.
- Jeśli akapity nie odpowiadają na pytanie, zwróć pustą listę zdań. To jest poprawna odpowiedź, nie porażka. Wyszukiwanie ZAWSZE zwraca jakieś akapity, nawet gdy żaden nie dotyczy pytania — lepiej powiedzieć "nie mam tego w źródłach" niż zlepić odpowiedź z tekstu o czymś innym.
- Nie wyciągaj wniosków. Jeśli źródło opisuje objawy choroby przy niskim pH, nie przerabiaj tego na zalecenie dotyczące odczynu gleby.
- Patrz na "poprzedni_fragment" — mówi, z jakiej części książki pochodzi akapit. Jeśli zalecenie dotyczy konkretnego problemu (choroby, szkodnika, zaburzenia), NAPISZ TO WPROST albo pomiń je zupełnie. "Podnieś pH gleby do około 6,0" w rozdziale o suchej zgniliźnie wierzchołkowej to sposób zapobiegania tej chorobie, a nie odpowiedź na pytanie, w jakim pH sadzić pomidory. Dobrze: "Przy suchej zgniliźnie wierzchołkowej podnosi się pH gleby do około 6,0". Źle: "Pomidory najlepiej sadzić w glebie o pH około 6,0".

Zasady języka — materiał czytają dorośli, którzy chcą się czegoś dowiedzieć:
- Jedno zdanie = jedna myśl. Zdanie powyżej 20 wyrazów rozbij na dwa.
- Odpowiadaj od razu. Nie zapowiadaj, o czym będziesz pisać, i nie podsumowuj na końcu.
- Zero doklejek bez treści: "co jest korzystne dla środowiska", "co ma istotne znaczenie", "warto pamiętać, że".
- Strona czynna i konkretnie: "rozsadę wysiewa się w drugiej połowie marca", nie "zaleca się rozpoczęcie produkcji rozsady od wysiewu nasion".
- Uważaj na przyimki: "W uprawie gruntowej pomidorów...", nie "Dla uprawy gruntowej pomidorów...".
- Całość do około dziesięciu zdań. Krócej jest lepiej, jeśli odpowiedź jest pełna.

NAJWAŻNIEJSZE — JĘZYK. Piszesz do ogrodnika, nie do urzędu. Czyta to człowiek starszej daty, który natychmiast wyłapuje sztuczne zdania.

Zakazane konstrukcje:
- "zalecane jest", "zaleca się", "należy", "powinien/powinno/powinna", "wskazane jest", "rekomenduje się" — zamiast tego pisz wprost: "podłoże ma być żyzne", "gleba jest lekko kwaśna";
- słowa z języka opracowań fachowych: "preferuje" (powiedz: lubi), "charakteryzuje się", "w przypadku" (powiedz: przy, gdy), "zapewnić odpowiednie warunki" (powiedz: zadbać o);
- rzeczowniki odczasownikowe tam, gdzie wystarczy czasownik: "produkcja rozsady" zamiast "rozsadę produkuje się", "stosowanie nawożenia" zamiast "nawozi się";
- zdania zaczynające się od tego, co zostało zalecone, zamiast od rzeczy, o której mowa;
- kalki z pytania: jeśli pytanie brzmi "w jakim pH najlepiej sadzić", nie zaczynaj odpowiedzi od "najlepiej sadzić w pH".

Tak wygląda ta sama treść powiedziana po ludzku:

Źle:    "Produkcję rozsady pomidorów do uprawy gruntowej należy rozpocząć od wysiewu nasion w drugiej połowie marca."
Dobrze: "Rozsadę na grunt wysiewa się w drugiej połowie marca."

Źle:    "Zalecane podłoże do siewu pomidorów ma pH 6,0–6,5."
Dobrze: "Do siewu weź podłoże o pH 6,0–6,5."

Źle:    "Pomidory najlepiej sadzić w glebie o pH około 6,0."
Dobrze: "Pomidor lubi glebę o odczynie około 6,0."

Źle:    "Zaleca się stosowanie podłoża o odczynie lekko kwaśnym."
Dobrze: "Pomidor lubi glebę lekko kwaśną."

Źle:    "W tunelach foliowych należy monitorować temperaturę, aby nie przekraczała 30°C."
Dobrze: "W tunelu pilnuj, żeby temperatura nie przekraczała 30°C."

"quote" ma być dosłownym cytatem ze źródła, ale "text" NIE może być jego kopią ani bliską parafrazą."""


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

Każdy kawałek podaje numery faktów, na których stoi. Jeśli następny kawałek nadal stoi
na tym samym fakcie, powtórz ten numer. Kawałek bez numeru to kawałek bez pokrycia
w książce — takiego nie wolno napisać.

Przykład dla faktów 0: "podlewać 2-3 razy w tygodniu, w czasie kwitnienia",
1: "częściej w upały i pod osłonami", 2: "lać pod krzew, nie moczyć liści":

  {"tekst": "Podlewaj 2-3 razy w tygodniu, a w upały i pod osłonami częściej", "fakty": [0, 1]}
  {"tekst": " — zawsze pod krzew, nigdy na liście.", "fakty": [2]}

Zwróć uwagę: trzy fakty dały jedno zdanie, nie trzy.

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
                },
                "required": ["tekst", "fakty"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["czesci"],
    "additionalProperties": False,
}

def normalize(text: str) -> str:
    """Do porownania cytatu z akapitem.

    Roznice w bialych znakach i rodzaju myslnika nie sa falszerstwem - PDF
    lamie wiersze gdzie popadnie, a model przepisuje z pamieci wzrokowej.
    W pierwszej wersji cytat odrzucany za jeden myslnik byl najczestsza
    przyczyna falszywych alarmow."""
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    text = text.replace(" ", " ").replace("„", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


# Ponizej tej dlugosci "cytat" niczego nie potwierdza - pojedyncze slowo
# znajdzie sie w niemal kazdym akapicie.
MIN_QUOTE_CHARS = 12


def quote_is_in_chunk(quote: str, chunk_text: str) -> bool:
    normalized = normalize(quote)
    if len(normalized) < MIN_QUOTE_CHARS:
        return False
    return normalized in normalize(chunk_text)


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


def answer_question(
    question: str,
    source_ids: list[int] | None = None,
    historia: list[tuple[str, str]] | None = None,
) -> dict:
    """Zwraca odpowiedz gotowa do pokazania: zdania z cytatami i lista zrodel."""
    do_wyszukania = przepisz_pytanie(historia or [], question)
    chunk_ids = search(do_wyszukania, source_ids=source_ids)
    if not chunk_ids:
        return _no_data()

    db = SessionLocal()
    try:
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

        fakty = _zbierz_fakty(do_wyszukania, context)
        if not fakty:
            return _no_data()

        raw = _napisz_z_faktow(do_wyszukania, fakty)
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


def _napisz_z_faktow(question: str, fakty: list[dict]) -> dict:
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
                "content": json.dumps({"pytanie": question, "fakty": do_napisania}, ensure_ascii=False),
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
        czesci.append({"text": czesc.get("tekst", ""), "zrodla": zrodla})
    return {"czesci": czesci}


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

        czesci.append(
            {
                "text": item.get("text", ""),
                # Kawalek bez zrodla to kawalek bez pokrycia - traktujemy go
                # tak samo jak zmyslony cytat.
                "verified": bool(zrodla) and all(z["verified"] for z in zrodla),
                "sources": zrodla,
                "styl": [],
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

    # Uwagi do jezyka liczymy na CALYM tekscie, rozbitym na prawdziwe zdania.
    # Kawalek to czesc zdania, wiec liczenie dlugosci czy powtorzonych poczatkow
    # na kawalkach dawaloby bzdury.
    return {
        "sentences": czesci,
        "styl": _uwagi_do_jezyka(sklej(czesci)),
        "sources": source_list,
        "note": None,
    }


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


_KONIEC_ZDANIA = re.compile(r"(?<=[.!?])\s+")


def _uwagi_do_jezyka(tekst: str) -> list[dict]:
    zdania = [z.strip() for z in _KONIEC_ZDANIA.split(tekst) if z.strip()]
    dodatkowe = sprawdz_odpowiedz(zdania)
    uwagi = []
    for numer, zdanie in enumerate(zdania):
        lista = sprawdz(zdanie) + dodatkowe.get(numer, [])
        if lista:
            uwagi.append({"text": zdanie, "styl": lista})
    return uwagi

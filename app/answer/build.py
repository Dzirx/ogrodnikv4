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


PISANIE_PROMPT = """Odpowiedz na pytanie, korzystając WYŁĄCZNIE z podanych faktów.

Nie widzisz zdań z książki, tylko suche informacje - i bardzo dobrze. Masz je powiedzieć własnymi słowami, tak jak powiedziałby ogrodnik, który się na tym zna i tłumaczy komuś, kto pyta.

Dla każdego zdania podaj "fakt_nr" - numer faktu, z którego korzystasz.

Język - czyta to człowiek starszej daty, który natychmiast wyłapuje sztuczne zdania:
- Jedno zdanie = jedna myśl, najwyżej kilkanaście wyrazów.
- Mów wprost: "pomidor lubi glebę lekko kwaśną", nie "zalecany odczyn gleby dla pomidora wynosi".
- Żadnych zwrotów urzędowych: "zaleca się", "należy", "powinno być", "wskazane jest", "preferuje", "w przypadku".
- Strona czynna: "rozsadę wysiewa się w marcu", nie "produkcję rozsady rozpoczyna się".
- Bez zapowiedzi i podsumowań. Bez doklejek w rodzaju "co jest korzystne dla środowiska".
- Odpowiedz krótko. Kilka zdań wystarczy; dziesięć to już dużo.

UKŁAD ODPOWIEDZI. Nie przerabiaj faktów jeden po drugim na osobne zdania — wyjdzie wyliczanka, a nie odpowiedź. Fakty mówiące o tej samej rzeczy w różnych sytuacjach połącz w jedną wypowiedź i pokaż różnicę między nimi.

Nie zaczynaj kolejnych zdań tak samo. Dwa zdania pod rząd od "Jeśli" to znak, że układasz listę zamiast mówić.

Źle:    "Jeśli chcesz uprawiać pomidory w gruncie, siej nasiona w drugiej połowie marca lub na początku kwietnia.
         Jeśli planujesz uprawę pod osłonami, wysiej nasiona na początku marca."
Dobrze: "Na grunt siej w drugiej połowie marca albo na początku kwietnia. Pod osłony wcześniej, bo już na początku marca."

Źle:    "Jeśli gleba jest zbyt kwaśna, zastosuj wapnowanie.
         Jeśli pH jest zbyt niskie, pomidory słabo pobierają składniki."
Dobrze: "Przy zbyt kwaśnej glebie pomidor słabo pobiera składniki — wtedy trzeba ją zwapnować."

Warunek z faktu wpleć w zdanie naturalnie ("pod osłony", "w gruncie", "przy suchej zgniliźnie"), nie jako osobną klauzulę na początku."""


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
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "fakt_nr": {"type": "integer"},
                },
                "required": ["text", "fakt_nr"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "chunk_id": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["text", "chunk_id", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
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
    napisane = json.loads(odpowiedz.choices[0].message.content).get("sentences", [])

    # Cytat wraca do zdania przez numer faktu - dzieki temu weryfikacja
    # dziala tak samo jak przedtem.
    zdania = []
    for zdanie in napisane:
        numer = zdanie.get("fakt_nr")
        if not isinstance(numer, int) or not 0 <= numer < len(fakty):
            continue
        fakt = fakty[numer]
        zdania.append(
            {
                "text": zdanie.get("text", ""),
                "chunk_id": fakt.get("chunk_id"),
                "quote": fakt.get("quote", ""),
            }
        )
    return {"sentences": zdania}


def _verify(raw: dict, by_id: dict, pages: dict, sources: dict) -> dict:
    """Sprawdza kazdy cytat i sklada odpowiedz do pokazania."""
    sentences = []
    used_chunks = []

    for item in raw.get("sentences", []):
        chunk = by_id.get(item.get("chunk_id"))
        if chunk is None:
            # Model wskazal akapit, ktorego mu nie dalismy.
            sentences.append(
                {
                    "text": item.get("text", ""),
                    "verified": False,
                    "styl": sprawdz(item.get("text", "")),
                    "source": None,
                }
            )
            continue

        verified = quote_is_in_chunk(item.get("quote", ""), chunk.text)
        page = pages[chunk.page_id]
        source = sources[chunk.source_id]
        if chunk.id not in used_chunks:
            used_chunks.append(chunk.id)

        sentences.append(
            {
                "text": item.get("text", ""),
                "verified": verified,
                # Uwagi do języka - klient czyta uchem człowieka starszej daty
                # i wyłapuje zdania urzędowe. Prompt o to prosi, ten kod
                # sprawdza, czy model posłuchał.
                "styl": sprawdz(item.get("text", "")),
                "source": {
                    "chunk_id": chunk.id,
                    "source_id": source.id,
                    "source_title": source.title,
                    "source_kind": source.kind,
                    "page": page.number,
                    "quote": item.get("quote", ""),
                    "marker": used_chunks.index(chunk.id) + 1,
                },
            }
        )

    if not sentences:
        return _no_data()

    # Uwagi widoczne dopiero w calej odpowiedzi (np. dwa zdania zaczynajace sie
    # tak samo) dokladamy do zdania, ktorego dotycza.
    for numer, uwagi in sprawdz_odpowiedz([z["text"] for z in sentences]).items():
        sentences[numer]["styl"] = sentences[numer].get("styl", []) + uwagi

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

    return {"sentences": sentences, "sources": source_list, "note": None}

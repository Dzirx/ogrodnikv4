"""Roznice miedzy ksiazkami - jedyne miejsce, w ktorym program pyta czlowieka.

Szukamy ich na faktach zebranych dla JEDNEGO pytania, nie skanujac ksiazek
parami. To nie jest oszczednosc, tylko warunek poprawnosci: fakty zebrane dla
jednego pytania z definicji dotycza tej samej rzeczy. Gdyby program sam
zestawial fragmenty ksiazek, musialby zgadywac, co z czym porownac - i wtedy
odczyn gleby pod pomidora trafilby na odczyn pod ogorka.

Falszywy spor kosztuje wiecej niz przeoczony. Przeoczony wroci przy kolejnym
pytaniu; falszywy kaze czlowiekowi rozstrzygac cos, co sporem nie jest, i po
kilku takich nikt juz nie zajrzy do tej zakladki.
"""

import hashlib
import json
import re

from openai import OpenAI
from sqlalchemy.orm import Session

from app.answer.cytaty import normalize, quote_is_in_chunk
from app.config import settings
from app.db.models import Chunk, Conflict, ConflictOption

_openai = OpenAI(api_key=settings.openai_api_key)

SZUKAJ_PROMPT = """Dostajesz fakty na jeden temat, wypisane z różnych książek ogrodniczych.
Wskaż te pary, które WYKLUCZAJĄ SIĘ nawzajem.

Para wyklucza się wtedy, gdy oba fakty mówią o tej samej rzeczy, w tych samych warunkach,
i nie mogą być jednocześnie prawdziwe. Ogrodnik musiałby wybrać jedno albo drugie.

To NIE jest para wykluczająca się:
- fakty o różnych warunkach uprawy ("pod osłonami" i "w gruncie", "w doniczce" i "w ziemi"),
- fakty o różnych rzeczach (odczyn gleby i odczyn wody, wysiew i sadzenie),
- fakty o różnych etapach uprawy albo różnych porach,
- fakty, które się uzupełniają: jeden ogólny, drugi go doprecyzowuje,
- zakresy liczbowe, które mają część wspólną,
- ta sama treść powiedziana innymi słowami.

Gdy masz jakąkolwiek wątpliwość, NIE zgłaszaj pary. Lepiej przeoczyć spór niż wymyślić.

Dla każdej pary podaj:
- "temat" — czego dotyczy spór, własnymi słowami, zawsze z nazwą rośliny,
  na przykład "optymalny odczyn gleby dla pomidora",
- "warunek" — w jakich warunkach, jeśli oba fakty go podają; inaczej pusty napis,
- "a" i "b" — numer faktu i samą sporną wartość, krótko: "5,5-6,5", "w drugiej połowie maja"."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "spory": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "temat": {"type": "string"},
                    "warunek": {"type": "string"},
                    "a": {
                        "type": "object",
                        "properties": {"nr": {"type": "integer"}, "wartosc": {"type": "string"}},
                        "required": ["nr", "wartosc"],
                        "additionalProperties": False,
                    },
                    "b": {
                        "type": "object",
                        "properties": {"nr": {"type": "integer"}, "wartosc": {"type": "string"}},
                        "required": ["nr", "wartosc"],
                        "additionalProperties": False,
                    },
                },
                "required": ["temat", "warunek", "a", "b"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["spory"],
    "additionalProperties": False,
}

# Zwroty, ktorymi model opisuje brak warunku. Bez tego "brak" i pusty napis
# wygladalyby jak dwa rozne warunki i spor przepadlby na bramce.
_BEZ_WARUNKU = {"", "brak", "brak warunku", "nie podano", "nie dotyczy", "ogolnie", "ogólnie", "-"}


def warunek(tekst: str | None) -> str:
    """Warunek sprowadzony do porownywalnej postaci."""
    oczyszczony = re.sub(r"[^\w\s]", " ", (tekst or "").lower())
    oczyszczony = re.sub(r"\s+", " ", oczyszczony).strip()
    return "" if oczyszczony in _BEZ_WARUNKU else oczyszczony


_LICZBA = re.compile(r"\d+(?:[.,]\d+)?")


def zakres(wartosc: str) -> tuple[float, float] | None:
    """Liczby z wartosci jako przedzial. None, gdy wartosc nie jest liczbowa."""
    liczby = [float(x.replace(",", ".")) for x in _LICZBA.findall(wartosc or "")]
    if not liczby:
        return None
    return min(liczby), max(liczby)


def zachodza_na_siebie(a: str, b: str) -> bool:
    """Czy dwa zakresy maja czesc wspolna.

    pH 5,5-6,5 i 6,0-7,0 nie wymagaja niczyjej decyzji - kazda wartosc z czesci
    wspolnej spelnia oba zalecenia. 5,5-6,5 i 7,0-7,5 wymagaja."""
    pierwszy, drugi = zakres(a), zakres(b)
    if pierwszy is None or drugi is None:
        return False
    return pierwszy[0] <= drugi[1] and drugi[0] <= pierwszy[1]


def odcisk(temat: str, wartosci: list[str]) -> str:
    """Odcisk sporu - zeby ten sam nie wrocil przy kolejnym pytaniu o to samo."""
    czesci = [normalize(temat)] + sorted(normalize(w) for w in wartosci)
    return hashlib.sha256("|".join(czesci).encode("utf-8")).hexdigest()[:64]


SPRAWDZ_PROMPT = """Dostajesz dwa zdania wypisane z dwóch różnych książek ogrodniczych.
Nie oceniaj od razu — najpierw je rozbierz.

"pytanie_pierwszego" i "pytanie_drugiego" — na jakie pytanie ogrodnika odpowiada każde
z nich. Krótko, własnymi słowami: "czym podlewać", "jak często podlewać", "jaki odczyn
gleby", "kiedy wysadzać rozsadę".

"to_samo_pytanie" — czy oba odpowiadają na TO SAMO pytanie. "Nie używaj zraszaczy"
odpowiada na pytanie, czego nie stosować; "podlewaj linią kroplującą" na pytanie, czym
podlewać. To dwa różne pytania, choć jeden temat.

"zakres_pierwszego" i "zakres_drugiego" — w jakich warunkach obowiązuje każde zdanie:
rodzaj uprawy (grunt, tunel, pojemnik), pogoda, pora dnia lub roku, faza rozwoju.
Bierz to wyłącznie z samego zdania, nie dopowiadaj. Gdy zdanie mówi o zasadzie ogólnej,
bez zawężenia — pusty napis.

"ten_sam_przypadek" — czy oba zakresy to ta sama sytuacja.

"da_sie_oba" — czy ogrodnik może zastosować OBA zalecenia naraz, w tym samym ogrodzie,
nie łamiąc żadnego. "Nie zraszaj" i "podlewaj kroplująco" da się spełnić jednocześnie.
"Podlewaj 2-3 razy w tygodniu" i "podlewaj codziennie" nie da się.

"ocena" — "spor" tylko wtedy, gdy spełnienie jednego ŁAMIE drugie. Przy jakiejkolwiek
wątpliwości "zgodne". Twoim zadaniem jest obalić spór, nie potwierdzić."""

_SCHEMA_SPRAWDZ = {
    "type": "object",
    "properties": {
        "pytanie_pierwszego": {"type": "string"},
        "pytanie_drugiego": {"type": "string"},
        "to_samo_pytanie": {"type": "boolean"},
        "zakres_pierwszego": {"type": "string"},
        "zakres_drugiego": {"type": "string"},
        "ten_sam_przypadek": {"type": "boolean"},
        "da_sie_oba": {"type": "boolean"},
        "ocena": {"type": "string", "enum": ["spor", "zgodne"]},
    },
    "required": [
        "pytanie_pierwszego",
        "pytanie_drugiego",
        "to_samo_pytanie",
        "zakres_pierwszego",
        "zakres_drugiego",
        "ten_sam_przypadek",
        "da_sie_oba",
        "ocena",
    ],
    "additionalProperties": False,
}


def rozstrzygaj_zakresy(zakres_a: str, zakres_b: str, ten_sam: bool) -> bool:
    """Czy dwa zdania mowia o tym samym przypadku.

    Reguly kodu, nie zdanie modelu - model podaje same zakresy, decyzja zapada
    tutaj. Powod byl konkretny: przy podlewaniu obie oceny uznaly za spor
    "unikaj podlewania wieczorem" i "w pojemnikach, w upalne dni podlewaj rano
    i wieczorem". Jedno mowi o pojemnikach w upaly, drugie o wieczorach w ogole."""
    a, b = warunek(zakres_a), warunek(zakres_b)
    # Jedno zdanie ogolne, drugie o wezszym przypadku - to doprecyzowanie.
    if bool(a) != bool(b):
        return False
    # Oba zawezone: musza zawezac do tego samego, inaczej nie ma o co sie sprzeczac.
    if a and b and not ten_sam:
        return False
    return True


def naprawde_sprzeczne(cytat_a: str, cytat_b: str) -> bool:
    """Druga, niezalezna ocena - na samych cytatach ze zrodel.

    Trzy warunki, kazdy sprawdzany osobno w kodzie. Model tylko rozbiera zdania
    na czesci: na jakie pytanie odpowiadaja, w jakich warunkach obowiazuja i czy
    da sie spelnic oba naraz.

    Trzeci warunek doszedl po fałszywym sporze zgloszonym z panelu: "nie uzywaj
    zraszaczy" kontra "podlewaj linia kroplujaca". Oba zdania sa ogolne i o tym
    samym temacie, wiec bramka zakresow ich nie zatrzymala - a odpowiadaja na
    dwa rozne pytania i da sie je spelnic jednoczesnie."""
    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SPRAWDZ_PROMPT},
                {"role": "user", "content": json.dumps({"pierwsze": cytat_a, "drugie": cytat_b}, ensure_ascii=False)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "ocena", "schema": _SCHEMA_SPRAWDZ, "strict": True},
            },
        )
        wynik = json.loads(odpowiedz.choices[0].message.content)
    except Exception:
        # Brak drugiej oceny znaczy brak sporu - nie pytamy czlowieka na slowo
        # jednego wywolania.
        return False

    return czy_spor(wynik)


def czy_spor(rozbior: dict) -> bool:
    """Decyzja kodu na podstawie tego, co model wypisal o obu zdaniach.

    Osobno, bo to jest miejsce, w ktorym zapada rozstrzygniecie - i jedyne,
    ktore da sie sprawdzic testem bez pytania modelu."""
    # Odpowiadaja na rozne pytania - moga byc oba prawdziwe, nie ma czego wybierac.
    if not rozbior.get("to_samo_pytanie"):
        return False
    # Da sie zastosowac oba naraz - to nie spor, tylko dwa zalecenia.
    if rozbior.get("da_sie_oba"):
        return False
    if not rozstrzygaj_zakresy(
        rozbior.get("zakres_pierwszego", ""),
        rozbior.get("zakres_drugiego", ""),
        bool(rozbior.get("ten_sam_przypadek")),
    ):
        return False
    return rozbior.get("ocena") == "spor"


def znajdz_konflikty(db: Session, pytanie: str, fakty: list[dict], by_id: dict[int, Chunk]) -> list[Conflict]:
    """Spory miedzy ksiazkami wsrod faktow zebranych dla tego pytania."""
    zrodla = {by_id[f["chunk_id"]].source_id for f in fakty if f.get("chunk_id") in by_id}
    if len(zrodla) < 2:
        # Jedna ksiazka nie spiera sie sama ze soba.
        return []

    do_porownania = [
        {
            "nr": numer,
            "tresc": fakt.get("tresc", ""),
            "warunek": fakt.get("warunek", ""),
            "ksiazka": by_id[fakt["chunk_id"]].source_id,
        }
        for numer, fakt in enumerate(fakty)
        if fakt.get("chunk_id") in by_id
    ]

    try:
        odpowiedz = _openai.chat.completions.create(
            model=settings.analysis_model,
            temperature=0,
            messages=[
                {"role": "system", "content": SZUKAJ_PROMPT},
                {"role": "user", "content": json.dumps({"pytanie": pytanie, "fakty": do_porownania}, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "spory", "schema": _SCHEMA, "strict": True}},
        )
        spory = json.loads(odpowiedz.choices[0].message.content).get("spory", [])
    except Exception:
        # Brak odpowiedzi to brak sporu, nie blad - pytanie ma dostac odpowiedz.
        return []

    utworzone = []
    for spor in spory:
        konflikt = _zbuduj(db, spor, fakty, by_id)
        if konflikt is not None:
            utworzone.append(konflikt)
    if utworzone:
        db.commit()
    return utworzone


def _zbuduj(db: Session, spor: dict, fakty: list[dict], by_id: dict[int, Chunk]) -> Conflict | None:
    """Bramki, przez ktore para musi przejsc, zanim stanie sie pytaniem do czlowieka."""
    strony = []
    for klucz in ("a", "b"):
        wskazanie = spor.get(klucz) or {}
        numer = wskazanie.get("nr")
        if not isinstance(numer, int) or not 0 <= numer < len(fakty):
            return None
        fakt = fakty[numer]
        chunk = by_id.get(fakt.get("chunk_id"))
        if chunk is None:
            return None
        strony.append((fakt, chunk, (wskazanie.get("wartosc") or "").strip()))

    (fakt_a, chunk_a, wartosc_a), (fakt_b, chunk_b, wartosc_b) = strony

    if not wartosc_a or not wartosc_b:
        return None
    # Spor jest miedzy ksiazkami. Jedna ksiazka mowiaca dwie rzeczy w dwoch
    # miejscach to prawie zawsze dwa rozne konteksty, nie sprzecznosc.
    if chunk_a.source_id == chunk_b.source_id:
        return None
    # Ten sam warunek albo oba bez warunku - inaczej to dwie rozne sytuacje.
    if warunek(fakt_a.get("warunek")) != warunek(fakt_b.get("warunek")):
        return None
    # Ta sama wartosc powiedziana inaczej nie jest sporem.
    if normalize(wartosc_a) == normalize(wartosc_b):
        return None
    if zachodza_na_siebie(wartosc_a, wartosc_b):
        return None
    # Ta sama bramka co przy odpowiedziach: bez cytatu w akapicie nie ma sporu.
    if not quote_is_in_chunk(fakt_a.get("quote", ""), chunk_a.text):
        return None
    if not quote_is_in_chunk(fakt_b.get("quote", ""), chunk_b.text):
        return None

    temat = (spor.get("temat") or "").strip()
    if not temat:
        return None
    warunek_sporu = (spor.get("warunek") or "").strip()
    if warunek_sporu:
        temat = f"{temat} ({warunek_sporu})"

    znak = odcisk(temat, [wartosc_a, wartosc_b])
    if db.query(Conflict).filter_by(fingerprint=znak).first() is not None:
        return None
    # Ostatnia bramka, najdrozsza - wolana dopiero, gdy para przeszla wszystkie
    # tanie sprawdzenia.
    if not naprawde_sprzeczne(fakt_a.get("quote", ""), fakt_b.get("quote", "")):
        return None

    konflikt = Conflict(subject=temat[:512], fingerprint=znak)
    konflikt.options = [
        ConflictOption(chunk_id=chunk_a.id, value=wartosc_a[:255], quote=fakt_a.get("quote", "")),
        ConflictOption(chunk_id=chunk_b.id, value=wartosc_b[:255], quote=fakt_b.get("quote", "")),
    ]
    db.add(konflikt)
    db.flush()
    return konflikt


def ustalenia_dla(db: Session, chunk_ids: list[int]) -> list[dict]:
    """Rozstrzygniecia czlowieka dotyczace akapitow, z ktorych wlasnie czerpiemy.

    Bez tego rozstrzygniecie sporu nie zmienialoby niczego w odpowiedziach -
    a zakladka obiecuje, ze program zapamieta i bedzie stosowal."""
    if not chunk_ids:
        return []
    konflikty = (
        db.query(Conflict)
        .join(ConflictOption, ConflictOption.conflict_id == Conflict.id)
        .filter(Conflict.status == "resolved", ConflictOption.chunk_id.in_(chunk_ids))
        .distinct()
        .all()
    )
    return [
        {"temat": k.subject, "wartosc": k.resolved_value, "wlasne": k.resolved_origin == "editorial"}
        for k in konflikty
        if k.resolved_value
    ]

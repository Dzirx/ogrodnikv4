# Tabele w PDF

Stan: **zaimplementowane.** Kod w `app/ingest/tabele.py`, podpięty w
`_extract_pages` (`app/ingest/pipeline.py`). Sprawdzone na żywo na stronie 8
programu ochrony pomidora gruntowego: 6/6 wpisów, wartości liczbowe (dawki,
karencje, liczba zabiegów) zgodne co do znaku z ręcznie spisanym wzorcem
(`_tab/wzorzec_s8.json`, poza repozytorium). Nazwy kolumn - patrz zastrzeżenie
niżej w "Jak to robimy".

## Problem

`page.get_text()` czyta tabelę wierszami, więc rozrywa ją na kawałki. W programie
ochrony pomidora nagłówek „Dawka na ha" stoi 280 znaków od wartości „1,5–3 l".
Taki tekst trafia do bazy jako akapit, w którym dawka nie należy już do żadnego
preparatu — i nic tego nie sygnalizuje.

Tabele są w dwóch z pięciu naszych plików: w obu programach ochrony (26 i 36 tabel)
oraz jedna w broszurze PODR. Książki ogrodnicze są prozą.

## Które strony dostają to traktowanie

`czy_tabela` (PyMuPDF `find_tables(strategy="lines")`) odsiewa fałszywe
wykrycia, ale progiem jest **liczba wierszy**, nie liczba kolumn. Pierwsza
wersja odrzucała strony z więcej niż 12 kolumnami — i razem ze śmieciem
(broszura PODR: dwie podpisane obok siebie fotografie, PyMuPDF widzi
pionową kreskę i zgłasza tabelę 1×2) odrzucała też prawdziwe tabele dawek:
program ochrony pomidora dzieli tę samą 9-kolumnową tabelę na 23–27 kolumn
przez szum w liniach siatki na części stron. Liczba kolumn, jaką zobaczył
kod, nie ma znaczenia — tabelę i tak czyta model patrzący na obraz. Próg
został: mniej niż dwa wiersze albo same puste komórki to nie tabela, więcej
— jest.

Zmierzone na plikach klienta: broszura PODR — 1 strona (zgodnie z tym, co
niżej), program ochrony pomidora gruntowego — 22 strony, szklarniowy — 33.
Obie książki bez tabel (Sułek, uprawa amatorska) — zero.

## Jak to robimy

Dwa wywołania modelu na stronę, `temperature=0` (bez tego nazwy kolumn w
jednym z przebiegów wyszły posklejane w nic nieznaczące złożenia zamiast
krótkich nazw z nagłówka — z `temperature=0` nie powtórzyło się to w kolejnych
próbach). Kod nie sprawdza treści i niczego nie składa — renderuje stronę,
wysyła, zapisuje wynik.

**Model 1 — czyta tabelę.** Dostaje stronę w dwóch postaciach: jako obraz i jako tekst
z `page.get_text()`. Obraz mówi, co z czym sąsiaduje; tekst mówi, jak się to pisze.
Zwraca nazwy kolumn — odczytane z tabeli, nie podane przez nas — i wiersze.

**Model 2 — poprawia i zapisuje.** Dostaje ten sam obraz i wynik modelu 1. Nie ocenia go,
tylko poprawia: pomylone kolumny, pasek sekcji wzięty za wartość, zmyślone nazwy nagłówków.
Potem zapisuje blok czytelnie: po jednym wpisie na środek, z nazwami kolumn przy wartościach,
a komórki scalone z wierszem wyżej jako „(jak wyżej)". Wypisuje też, co zmienił.

Poprawianie jest lepsze od odrzucania: na stronie 8 model 1 wymyślił nazwy kolumn i wsadził
pasek „TRIAZYNONY – grupa C1 wg HRAC 5" w kolumnę z dawką. Model 2 patrząc na obraz usunął
ten pasek z dawki i odtworzył wartości — `Devrinol 450 S.C.`, `napropamid – 450 g/l`,
`2,5–3 l`, karencja `nd`. Wersja, która zamiast poprawiać zgłaszała niezgodność, wyrzucała
przy tym całą stronę.

**Kod** — render strony, dwa wywołania, `Chunk(source_id, page_id, seq, text)`.
Dalej embedding, Qdrant, cytat ze stroną, konflikty — bez zmian.

## Dlaczego kod nie sprawdza wartości

Decyzja klienta z 23 września: ufamy modelom, kod wypada.

Podstawa: każda kontrola, jaką napisałem, myliła się częściej niż model. Sprawdzanie
par sąsiednich słów zgłaszało błąd na poprawnych danych, bo model wstawia przecinki
między nazwami. Sprawdzanie zdania słowo po słowie odpadało na odmianie („w fazie",
„oznaczonej jako"). Podstawianie wartości ze scalonych komórek wymagało od kodu
rozstrzygnięcia, czy pustka jest scaleniem, czy brakiem — czego nie umie.

Cena tej decyzji, powiedziana wprost: `Devrinol 480` zamiast `450` wejdzie do bazy,
jeśli oba modele przepuszczą ten błąd. W pomiarach znikał, gdy model dostawał tekst
strony obok obrazu, ale gwarancji nie ma. Dawki z tych tabel wymagają oka redaktora
przed publikacją.

## Dlaczego blok, a nie osobne zdania

Sprawdzone na żywo: model piszący odpowiedź radzi sobie z całym blokiem tabeli lepiej
niż z rozbitymi zdaniami. Zapytany o dawkę Sencora, gdy w bloku są dwie, odpowiedział:
„standardowo 0,6 l na ha, natomiast w metodzie dawek dzielonych 0,35 l na ha".
Zapytany o sposób działania, podał wartość ze scalonej komórki stojącej przy innym
preparacie — sam skojarzył „(jak wyżej)".

Ten sam blok zapisany surowo, z pionowymi kreskami i pustymi polami, dał „Nie ma"
na pytanie o dawkę. Czytelność zapisu decyduje, nie ilość obróbki.

## Dlaczego oba źródła naraz

Sam obraz nie wystarcza — model przekręca nazwy własne. Na stronie 8 bez tekstu
zmyślił cztery nazwy z sześciu: `Devrinol 480` zamiast `450`, `Evore` zamiast `Evora`,
`Metryzyna` zamiast `Metrybuzyna`, `Ramezs` zamiast `Ramzes`. Wartości liczbowe
(dawki, karencje) miał przy tym poprawne.

Sam tekst też nie wystarcza — jest spaghetti i nie widać z niego kolumn.

Razem: **6/6 wpisów i 36/36 pól** wobec wzorca spisanego ręcznie ze strony 8.

## Co trafia do baz

Blok z modelu 2 zapisujemy jako zwykły akapit — ale jeden na całą stronę, nie
przez zwykły podział na akapity. `split_into_paragraphs` tnie po pustych
liniach i po 700 znakach; przepuszczony przez nią blok tabeli rozpadłby się
dokładnie tak, jak rozrywa go `page.get_text()` — każdy wpis osobno, bez
wspólnego kontekstu, którego dotyczy rozdział wyżej ("Dlaczego blok, a nie
osobne zdania"). Strona z tabelą pomija ten krok i na tym nasza rola się
kończy:

```python
db.add(Chunk(source_id=..., page_id=..., seq=..., text=blok))   # Postgres
db.commit()
index_source(source_id)                                          # Qdrant
```

`index_source` liczy embedding i wysyła go do Qdranta z payloadem, nie odróżniając
akapitu z tabeli od akapitu prozy — bo to ten sam rekord. Dzięki temu bez żadnej zmiany
działają: wyszukiwanie znaczeniowe, wyszukiwanie po słowach, cytat z numerem strony,
podgląd strony i wykrywanie różnic między książkami.

Nie ma wyłącznika odrzucającego stronę. Model 2 poprawia to, co widzi, i zapisuje;
jeśli się pomyli, błąd wejdzie do bazy. To cena decyzji z rozdziału wyżej.

## Czego nie robimy

- **Tabel będących zdjęciem.** Nie ma warstwy tekstowej, więc nie ma czym podeprzeć
  pisowni, a OCR odczytał `1,5–3 l` jako `15-31`, czyli dziesięciokrotnie zawyżoną dawkę
  środka ochrony roślin. Decyzja klienta: nie obsługujemy.
- **Zgadywania nazw kolumn.** Gdy tabela ich nie ma, akapit składamy z samych wartości.
  Zmyślona nazwa jest gorsza niż jej brak.

## Co zostało do zrobienia

1. **Nagłówki na stronach kontynuacji.** Decyzja z 23 września: na razie **nie naprawiamy**,
   ruszamy z tym, co jest.
   Tabela dawek ciągnie się od strony 7 do 15, ale nazwy kolumn są tylko na pierwszej;
   dalej zostaje sam wiersz numeracji `1…9`. Oba modele wypełniają wtedy lukę zmyśleniem:
   `Nazwa handlowa`, `Kategoria`, `Okres prewencji` zamiast `Środek ochrony roślin`,
   `Karencja (dni)`, `Dodatkowe informacje`. Wartości są przy tym poprawne, ale stoją pod
   złą etykietą — `Kategoria: 30` zamiast `Karencja: 30` — więc pytanie o karencję nie
   trafi w ten akapit.

   Rozwiązanie nasuwa się samo — zapamiętać nagłówki przy pierwszej stronie tabeli
   i podawać kolejnym — ale ma pułapkę, przez którą je odłożyliśmy. W programie
   szklarniowym nagłówki są na stronach **7, 16 i 34**, czyli to trzy różne tabele.
   Reguła „weź z ostatniej strony, która je miała" przypnie nazwy kolumn tabeli chorób
   do tabeli szkodników — a wszystko będzie brzmiało wiarygodnie, bo etykiety pochodzą
   z dokumentu. Gorsze niż zmyślenie.

   Gdy do tego wrócimy: przekazywać nagłówki jako **podpowiedź, nie nakaz** („poprzednia
   strona tej tabeli miała takie kolumny; jeśli na obrazie widzisz inną tabelę, zignoruj"),
   albo dołożyć obraz pierwszej strony tabeli. W obu wypadkach rozstrzyga model, nie reguła
   w kodzie. Czego nie umiemy zagwarantować: te tabele są składane jednym szablonem, więc
   chwasty, choroby i szkodniki różnią się właściwie tylko nazwą pierwszej kolumny.
2. **Koszt drugiego modelu.** Sprawdzenie i napisanie zdań dla sześciu wierszy kosztowało
   1737 tokenów. Do zmierzenia na pełnej stronie, zanim powiemy, ile kosztuje książka.
3. **Wzorce do mierzenia.** Mamy jeden, ręcznie spisany (`_tab/wzorzec_s8.json`, poza
   repozytorium). Bez drugiego nie da się powiedzieć, czy trzymamy 80%, o które prosił
   klient — jedna strona to za mało.

## Czego próbowaliśmy i odrzuciliśmy

Wszystko sprawdzone na tych samych plikach, wszystko gorsze od powyższego:

- **Most z tagów struktury PDF przez MCID do tekstu** — wpisy grupuje dobrze, ale gubi
  końcówki linii w szerokich kolumnach (81% słów) i psuje tabelę BBCH.
- **Granice kolumn liczone ze środków cyfr numeracji** — przybliżone, więc wycinanie
  tekstu wchodzi w sąsiednią kolumnę: `nd głębokość 3 na niektóryc`.
- **pdfplumber z granicami wierszy z tagów** — czysty tekst, ale 5/6 wpisów i 60% pól.
- **Sprawdzanie par sąsiednich słów w tekście strony** — daje fałszywe alarmy, bo model
  wstawia przecinki między nazwami, których w PDF nie ma. Zgłaszało błąd na poprawnych
  danych.
- **Cięcie tekstu po pionowych kreskach** — zakłada, że tabela ma ramki. Bez nich nie
  działa wcale.

# Tabele w PDF

Stan: **rozpoznane i zmierzone, kod jeszcze nie napisany.**

## Problem

`page.get_text()` czyta tabelę wierszami, więc rozrywa ją na kawałki. W programie
ochrony pomidora nagłówek „Dawka na ha" stoi 280 znaków od wartości „1,5–3 l".
Taki tekst trafia do bazy jako akapit, w którym dawka nie należy już do żadnego
preparatu — i nic tego nie sygnalizuje.

Tabele są w dwóch z pięciu naszych plików: w obu programach ochrony (26 i 36 tabel)
oraz jedna w broszurze PODR. Książki ogrodnicze są prozą.

## Jak to robimy

Dwa wywołania modelu na stronę. Kod nie sprawdza treści i niczego nie składa —
renderuje stronę, wysyła, zapisuje wynik.

**Model 1 — czyta tabelę.** Dostaje stronę w dwóch postaciach: jako obraz i jako tekst
z `page.get_text()`. Obraz mówi, co z czym sąsiaduje; tekst mówi, jak się to pisze.
Zwraca nazwy kolumn — odczytane z tabeli, nie podane przez nas — i wiersze.

**Model 2 — sprawdza i zapisuje.** Dostaje ten sam obraz i wynik modelu 1. Potwierdza,
czy odczyt zgadza się z tabelą, i zapisuje blok czytelnie: po jednym wpisie na środek,
z nazwami kolumn przy wartościach, a komórki scalone z wierszem wyżej jako „(jak wyżej)".

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

## Kiedy odrzucamy

Wiersz wypada w całości, gdy zawiedzie którakolwiek z kontroli: wartość nie występuje
w tekście strony, model 2 zgłosi niezgodność odczytu albo zdanie ma inne liczby niż wiersz. Wpis nie wchodzi
do bazy częściowo, bo akapit bez nazwy preparatu, za to z dawką, wygląda na kompletny
i jest groźniejszy niż jego brak.

Sprawdzone: przy zmyślonych nagłówkach na stronie 13 mechanizm odrzucił wszystkie
dziewięć wierszy — do bazy nie weszło nic.

## Czego nie robimy

- **Tabel będących zdjęciem.** Nie ma warstwy tekstowej, więc nie ma czym podeprzeć
  pisowni, a OCR odczytał `1,5–3 l` jako `15-31`, czyli dziesięciokrotnie zawyżoną dawkę
  środka ochrony roślin. Decyzja klienta: nie obsługujemy.
- **Zgadywania nazw kolumn.** Gdy tabela ich nie ma, akapit składamy z samych wartości.
  Zmyślona nazwa jest gorsza niż jej brak.

## Co zostało do zrobienia

1. **Nagłówki na stronach kontynuacji.** Tabela dawek ciągnie się od strony 7 do 15,
   ale nazwy kolumn są tylko na pierwszej; dalej zostaje sam wiersz numeracji `1…9`.
   Bez nich model wymyśla nazwy (`Nazwa środka`, `Termin stosowania`) i wszystko
   przepada na kontroli. Nagłówki trzeba zapamiętać przy pierwszej stronie tabeli
   i podawać kolejnym.
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

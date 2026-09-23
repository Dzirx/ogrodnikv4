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

Dwa wywołania modelu na stronę i kod, który niczego nie interpretuje.

**Model 1 — czyta tabelę.** Dostaje stronę w dwóch postaciach: jako obraz i jako tekst
z `page.get_text()`. Obraz mówi, co z czym sąsiaduje; tekst mówi, jak się to pisze.
Zwraca nazwy kolumn (odczytane z tabeli, nie podane przez nas) i wiersze. Komórka pusta,
bo scalona z wierszem wyżej, wraca jako `null`.

**Model 2 — sprawdza i pisze.** Dostaje ten sam obraz i wynik modelu 1. Odpowiada, czy
odczyt zgadza się z tabelą, a potem układa z każdego wiersza jedno zdanie po polsku.
Zdanie pisze model, bo kod nie rozumie treści i skleiłby listę pól, której nikt nie
przeczyta i która źle się wyszukuje.

**Kod — pilnuje, nie tworzy.** Robi trzy rzeczy:

1. podstawia pod `null` wartość z wiersza wyżej z tej samej kolumny,
2. sprawdza, czy każda wartość z modelu 1 występuje w tekście strony — to wyłapuje
   zmyślone nazwy,
3. sprawdza, czy zdanie z modelu 2 zawiera dokładnie te liczby, co wiersz — ani jednej
   mniej, ani jednej więcej.

Trzecia kontrola jest najważniejsza, bo liczby w tych tabelach to dawki i karencje.
Kod nie rozumie zdania, ale rozpozna, że „w dawce 25 l na ha" ma liczbę, której w wierszu
nie było, a zgubiło `2,5–3`. Nie da się tego obejść gładkim stylem.

Sprawdzanie zdania słowo po słowie nie działa — model odmienia wyrazy i dodaje spoiwo
(„w fazie", „oznaczonej jako"), więc każde poprawne zdanie wyglądałoby na zmyślone.

**Zapis jak każdy inny akapit:** `Chunk(source_id, page_id, seq, text)`. Dalej embedding,
Qdrant, cytat ze stroną, konflikty — bez zmian.

Kod nie wie, czy tabela ma kreski, ile ma kolumn ani czego dotyczy.

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

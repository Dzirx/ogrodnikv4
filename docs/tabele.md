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

Jedno wywołanie modelu na stronę:

1. **Renderujemy stronę jako obraz.**
2. **Wysyłamy modelowi obraz i tekst tej samej strony naraz.** Obraz mówi, co z czym
   sąsiaduje; tekst mówi, jak się to pisze.
3. **Model zwraca nagłówki kolumn i wiersze** — nazwy kolumn odczytuje z tabeli,
   nie dostaje ich od nas. Komórka pusta, bo scalona z wierszem wyżej, wraca jako `null`.
4. **Kod robi trzy rzeczy i nic więcej:** podstawia pod `null` wartość z wiersza wyżej,
   sprawdza, czy każda wartość występuje w tekście strony, i składa zdanie
   `nazwa kolumny: wartość; …`.
5. **Zapis jak każdy inny akapit:** `Chunk(source_id, page_id, seq, text)`. Dalej
   embedding, Qdrant, cytat ze stroną, konflikty — bez zmian.

Kod nie wie, czy tabela ma kreski, ile ma kolumn ani czego dotyczy.

## Dlaczego oba źródła naraz

Sam obraz nie wystarcza — model przekręca nazwy własne. Na stronie 8 bez tekstu
zmyślił cztery nazwy z sześciu: `Devrinol 480` zamiast `450`, `Evore` zamiast `Evora`,
`Metryzyna` zamiast `Metrybuzyna`, `Ramezs` zamiast `Ramzes`. Wartości liczbowe
(dawki, karencje) miał przy tym poprawne.

Sam tekst też nie wystarcza — jest spaghetti i nie widać z niego kolumn.

Razem: **6/6 wpisów i 36/36 pól** wobec wzorca spisanego ręcznie ze strony 8.

## Kiedy odrzucamy

Jedna wartość niezgodna z tekstem strony unieważnia **cały wiersz**. Wpis nie wchodzi
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
2. **Druga ocena.** Na tabeli faz BBCH model raz odczytał układ poprawnie, raz rozbił
   komórkę `00 000` na dwie kolumny. Drugi model, pytany nie „przeczytaj", tylko
   „czy ten odczyt się zgadza", wykrył ten błąd. Do sprawdzenia, czy warto za to płacić
   drugim wywołaniem na każdą stronę.
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

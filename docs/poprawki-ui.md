# Poprawki interfejsu — zgłoszenia z przeglądu

Wszystkie cztery rzeczy istnieją w kodzie i działają po stronie serwera.
Problem jest w interfejsie: nie widać ich albo nie da się do nich wrócić.

## 1. Z podglądu nie ma powrotu do rozmowy

Podgląd otwiera się przez `?podglad=N` w adresie. Żeby go zamknąć, trzeba
ręcznie skasować parametr — nie ma żadnego przycisku.

**Naprawa:** krzyżyk w nagłówku kolumny podglądu, wracający do czystego adresu
rozmowy. Rozmowa i tak jest widoczna obok, więc wątek się nie gubi.

## 2. Nie widać, z których książek korzysta rozmowa

Wybór książek jest tylko w formularzu nowego pytania. Po wejściu w istniejący
wątek nie widać, co było zaznaczone, ani nie da się tego zmienić.

**Naprawa:** w lewej kolumnie, pod tytułem otwartej rozmowy, lista jej źródeł
z możliwością zmiany zaznaczenia. Zmiana obowiązuje od następnego pytania —
wcześniejsze odpowiedzi opierały się na tym, co było zaznaczone wtedy, i nie
wolno tego zmieniać wstecz.

## 3. Książki nie da się obejrzeć w panelu

W zakładce Źródła tytuł prowadzi do surowego pliku PDF w nowej karcie.
Wychodzi się z panelu i wraca przyciskiem przeglądarki.

**Naprawa:** własny ekran źródła — strony jako obrazy, przewijane w panelu,
z listą akapitów. Link do oryginalnego pliku zostaje, ale jako opcja.

## 4. Etykiety nie służą do niczego

Można je nadać przy dodawaniu źródła i widać je na liście, ale przy pytaniu
wybiera się pojedyncze książki. Przy kilkudziesięciu źródłach to bez sensu.

**Naprawa:** przy wyborze książek grupowanie po etykietach z zaznaczaniem całej
grupy naraz — tak jak w NotebookLM zaznacza się wszystkie źródła jednym
kliknięciem.

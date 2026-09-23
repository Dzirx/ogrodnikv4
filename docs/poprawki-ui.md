# Poprawki interfejsu — zgłoszenia z przeglądu

Stan: **wszystkie cztery zrobione.** Dokument zostaje jako zapis tego, co i
dlaczego zgłoszono — poprawki poszły commit po commicie zaraz po spisaniu tej
listy.

Wszystkie cztery rzeczy istniały w kodzie i działały po stronie serwera.
Problem był w interfejsie: nie było ich widać albo nie dało się do nich wrócić.

## 1. Z podglądu nie ma powrotu do rozmowy — ✅ zrobione

Podgląd otwiera się przez `?podglad=N` w adresie. Żeby go zamknąć, trzeba
ręcznie skasować parametr — nie ma żadnego przycisku.

**Naprawa:** krzyżyk w nagłówku kolumny podglądu, wracający do czystego adresu
rozmowy. Rozmowa i tak jest widoczna obok, więc wątek się nie gubi.

Zrobione w `app/api/templates/chat.html` (krzyżyk „✕" w nagłówku kolumny
podglądu), commit `007ac62`.

## 2. Nie widać, z których książek korzysta rozmowa — ✅ zrobione

Wybór książek jest tylko w formularzu nowego pytania. Po wejściu w istniejący
wątek nie widać, co było zaznaczone, ani nie da się tego zmienić.

**Naprawa:** w lewej kolumnie, pod tytułem otwartej rozmowy, lista jej źródeł
z możliwością zmiany zaznaczenia. Zmiana obowiązuje od następnego pytania —
wcześniejsze odpowiedzi opierały się na tym, co było zaznaczone wtedy, i nie
wolno tego zmieniać wstecz.

Zrobione, ale nie dokładnie tam, gdzie zakładała naprawa: sekcja „Czerpie z:
X z Y książek" wylądowała w stopce środkowej kolumny (rozmowy), nie w lewej
pod tytułem — lewa kolumna została wyłącznie historią wątków (`781eca6`).
Działa tak samo: widać zakres, da się go zmienić, zapisuje się w tle bez
przeładowania strony (`83e4f10`, `08b9ec9`).

## 3. Książki nie da się obejrzeć w panelu — ✅ zrobione

W zakładce Źródła tytuł prowadzi do surowego pliku PDF w nowej karcie.
Wychodzi się z panelu i wraca przyciskiem przeglądarki.

**Naprawa:** własny ekran źródła — strony jako obrazy, przewijane w panelu,
z listą akapitów. Link do oryginalnego pliku zostaje, ale jako opcja.

Zrobione w `app/api/templates/zrodlo.html`, commit `a01f0e2`.

## 4. Etykiety nie służą do niczego — ✅ zrobione

Można je nadać przy dodawaniu źródła i widać je na liście, ale przy pytaniu
wybiera się pojedyncze książki. Przy kilkudziesięciu źródłach to bez sensu.

**Naprawa:** przy wyborze książek grupowanie po etykietach z zaznaczaniem całej
grupy naraz — tak jak w NotebookLM zaznacza się wszystkie źródła jednym
kliknięciem.

Zrobione w `app/api/templates/chat.html` (makro `wybor_zrodel`), commit
`c6e5303`.

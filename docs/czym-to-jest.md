# Ogrodnik — druga wersja

## Po co druga wersja

Pierwsza (`~/projekt/ogrodnikv3`) rozwiązywała problem, którego klient nie ma.
Modelowała wiedzę w bazie: pojęcia, wymiary warunków, podpisy kontekstu, fakty
ze slotami podstawianymi do tekstu. Skutki, wszystkie zgłoszone przez klienta:

- 340 pojęć, z czego większość pusta; 26 wymiarów warunków wymyślonych przez AI,
  w dużej części duplikatów (`temperature`, `temperatura`, `soil_temperature`);
- konflikt mieszający kiełkowanie nasion z kiełkowaniem zarodników grzyba;
- „w zakresie od pH 5,5-6,5 do pH 5,5-6,5" — slot podstawiony dwa razy;
- kolejka z 51 pozycjami, przy których redaktor nie wiedział, co kliknąć;
- cztery zakładki, z których trzy go nie obchodziły.

Zdanie klienta ze spotkania 14 września: **„to nie ja mam być niewolnikiem tego
AI, tylko AI ma pracować na mnie"**.

## Co ma robić

Cztery rzeczy, nic więcej:

1. **Źródła.** Wgrywa plik albo wkleja tekst, nadaje etykiety tematyczne.
   Jedno źródło obsługuje wiele tematów — dodaje się je raz.
2. **Pytanie i odpowiedź.** Zadaje pytanie, dostaje krótką odpowiedź. Po lewej
   tekst, po prawej strona PDF, z której pochodzi cytat — klika i od razu widzi
   źródło, zamiast go szukać.
3. **Konflikty.** Gdy dwa źródła podają inną wartość tej samej rzeczy, program
   pyta. Redaktor wybiera jedną albo wpisuje własną, która odtąd obowiązuje.
   **To jedyne miejsce, w którym program go o cokolwiek pyta.**

## Podział pracy: model i kod

Odwrotnie niż w pierwszej wersji.

**Model** rozstrzyga wszystko, co dotyczy znaczenia: czego dotyczy zdanie, jaka
jest w nim wartość, czy dwa zdania mówią o tej samej rzeczy co innego. Nie ma
słownika pojęć ani wymiarów warunków — nie ma czego zaśmiecić.

**Kod** robi jedną rzecz, za to pewnie: sprawdza, czy cytat naprawdę występuje
w akapicie, na który się powołuje. Jedno porównanie tekstu, zero kosztu, pewność
której model nie da.

Cena tej zamiany, powiedziana wprost: model może przeoczyć sprzeczność, której
deterministyczne porównanie by nie przeoczyło. W zamian znika cała maszyneria,
która produkowała fałszywe konflikty i pytania bez odpowiedzi.

## Czego świadomie nie ma

- Pojęć, wymiarów warunków, podpisów kontekstu.
- Slotów podstawianych do tekstu — model cytuje akapit wprost.
- Kolejek innych niż konflikty wartości.
- PDF-a odpowiedzi. Redaktor czyta ją na ekranie; jak zechce gdzieś wkleić,
  zaznaczy i skopiuje. PDF był elementem pierwszej wersji, gdzie materiał był
  dokumentem do wydruku z bibliografią — tutaj nie ma do czego.
- Zdjęć i tabel będących obrazem — tak jak w pierwszej wersji.
  (OCR stron, na których tekst siedzi w obrazie, doszedł później;
  tabele z warstwy tekstowej opisuje `tabele.md`.)

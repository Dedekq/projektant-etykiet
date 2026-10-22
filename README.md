# Projektant etykiet

Program okienkowy do projektowania i drukowania etykiet (wzorowany na BarTenderze).
Plik do uruchomienia: `dist/ProjektantEtykiet.exe` (nie wymaga instalacji). Przykład: `testout/przyklad.etk`.

## Elementy
- **Tekst** wielowierszowy — dwuklik = edycja. Zaznacz słowo i użyj paska formatowania (czcionka, rozmiar, B/I/U, kolor, „biały na czarnym”). Bez edycji format dotyczy całego tekstu. Szerokość (zawijanie), wyrównanie, interlinia w panelu.
- **Kody kreskowe**: EAN-13, EAN-8, UPC-A, EAN-14, Code 128, GS1-128, Code 39, ITF, Codabar. Moduł X w mm, wysokość kresek, tekst pod kodem.
- **Kody 2D**: QR, Micro QR, DataMatrix, GS1 DataMatrix (dane jako `(01)05901234123457(10)PARTIA`).
- Linia, prostokąt (zaokrąglenie), elipsa, obraz.
- Układ: wyrównywanie, kolejność, kopiuj/wklej/duplikuj, strzałki (0,1 mm; z Shift 1 mm), przyciąganie do siatki, cofnij/ponów, blokada.

## Zmienne (w tekście i kodach)
`{DATA}`, `{DATA+365}` (np. data przydatności), `{CZAS}`, `{LICZNIK}`, `{LICZNIK:6}` (z zerami), `{NazwaKolumny}` z pliku CSV (separator `;` lub `,`, UTF-8).

## Druk (przycisk „Rozmiar i drukarka”, Ctrl+L)
- **TSC / TSPL** (główna: TSC MH341, 300 dpi) — wysyłka prosto na USB, bez instalowania sterownika; także kolejka Windows (RAW) lub TCP. Kalibracja nośnika = GAPDETECT. Przerwa między etykietami (domyślnie 3 mm) jest wysyłana zawsze — bez niej drukarka nie synchronizuje się z przerwami. Nawijanie = `SET REWIND ON` (wewnętrzny nawijak). Zakładka „Rolka i nawijanie” i okno druku pokazują rysunek rolki z kierunkiem wysuwu.
  - Rolka z etykietami 70 × 50 wychodzącymi krótszym bokiem: kierunek na rolce **90°**.
  - Korekta zmierzona w tym zakładzie: w prawo **−1,25 mm**, w dół **+2,5 mm** (domyślna dla kafelka TSC; w innych zakładach zmień w zakładce „Marginesy i kalibracja”).
  - Przesunięcie w poprzek głowicy idzie poleceniem `SHIFT` (±25 mm), wzdłuż wysuwu — w obrazie. Tylko tak nic nie jest ucinane (sprawdzone wydrukami na MH341).
  - Test akceptacyjny: `python etykieta/acceptance.py testout` (drukuje 3 etykiety; `DRY=1` — do pliku zamiast na drukarkę).
- **Zebra / ZPL** — wysyłka RAW do kolejki Windows albo TCP (port 9100). Tryb wyjścia: odrywanie, odklejanie, nawijanie (rewind), obcinarka, aplikator; rodzaj nośnika (przerwa / znacznik / ciągła); zaczernienie, prędkość, korekta odrywania, kalibracja nośnika (~JC).
- **Sterownik Windows** (Datamax E-4304 i inne) — rysowanie wektorowe, rozmiar strony = etykieta.
- W obu metodach: kierunek na rolce (0/90/180/270°), lustro, przesunięcie X/Y w mm, kilka etykiet w poprzek rolki z odstępem.
- Moduły kodów są wyrównywane do pełnych punktów głowicy (np. 0,33 mm na 203 dpi → 3 pkt = 0,375 mm); dokumentacja wymiarowa podaje wartość efektywną.
- Podgląd ZPL pokazuje dokładny obraz wysyłany na głowicę. „Zapisz ZPL…” zapisuje zadanie do pliku.

## Eksport
- **Dokumentacja wymiarowa (PDF)** — rysunek w skali z wymiarami etykiety, numerami elementów i tabelą: X, Y, szerokość, wysokość, obrót, czcionki (pt, wysokość wersalika i x w mm), parametry kodów (moduł, wysokość, powiększenie EAN, wersja QR).
- PDF wektorowy, SVG, PNG w wybranej rozdzielczości.

## Budowanie .exe
```bash
python -m pip install PySide6 python-barcode segno pystrich qtawesome pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name ProjektantEtykiet --distpath dist --collect-data qtawesome etykieta/app.py
```
Autotest: `python etykieta/selftest.py testout`

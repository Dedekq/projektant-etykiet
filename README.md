# Projektant etykiet — Label Designer

[English](#english) · [Polski](#polski)

---

## English

A Windows desktop app for designing and printing product labels, in the spirit of BarTender. Written in Python + PySide6 (Qt), shipped as a single `ProjektantEtykiet.exe` that needs no installation.

### Features
- **Text**: multi-line, with per-word formatting (font, size, bold/italic/underline, colour, white-on-black). You can set wrap width, alignment and line spacing. Text on screen is laid out exactly as it prints, with no rounding to screen pixels.
- **1D barcodes**: EAN-13, EAN-8, UPC-A, EAN-14, Code 128, GS1-128, Code 39, ITF and Codabar. Module width is in mm and bars are snapped to whole printer-head dots. EAN digits sit under their own symbol characters.
- **2D codes**: QR, Micro QR, DataMatrix, GS1 DataMatrix (`(01)…(10)…`), PDF417 and Aztec.
- **Shapes and images**: lines, rectangles (rounded), ellipses and images.
- **Editing**: mouse resize handles, align, z-order, copy/paste, nudge with arrow keys, snap to grid, undo/redo and lock.
- **Variables**: `{DATA}`, `{DATA+365}`, `{CZAS}`, `{LICZNIK:6}` and `{Column}` from a data source.
- **Print data**: Excel (.xlsx), CSV, ODBC databases or SQLite, with one label per row. Passwords are never stored in the project.
- **Printing**:
  - TSC/TSPL straight over USB, no driver needed. Covers gap sync, rewinder, `SHIFT` offset and media calibration.
  - Zebra/ZPL over a RAW queue or TCP 9100.
  - Any Windows printer driver.
  - Also: roll direction (0/90/180/270°), output mode (tear-off, peel-off, rewind, cutter, applicator), X/Y offsets and several labels across the roll.
  - A roll preview shows how labels leave the printer.
- **Export**: a dimension drawing (PDF) with a measurement table covering positions, font sizes and cap heights, barcode module and magnification. Also vector PDF, SVG and PNG.
- **Project files `.etk`**: JSON with images embedded. Double-click opens them, because the .exe registers the file type for the current Windows user.
- **BarTender import (`.btw`)**: opens BarTender 2022 labels without BarTender installed.
  - Reads label size, rich text (bold runs, wrapping, alignment, the nine anchor points), EAN/UPC/Code 128/Code 39, and pictures.
  - A QR code stored as an SVG picture becomes an editable QR code.
  - The result is saved as `.etk`. The original `.btw` file is never modified.
  - The format is closed and was worked out from sample files. Anything unrecognised is skipped and listed after import.
  - Printer-resident fonts such as TSC Sans Serif are replaced with Arial, which is slightly wider.
- **Save for BarTender (`.btw`)**: File → Save for BarTender writes a new `.btw` file from a label that was opened from `.btw`.
  - The original file is kept inside the project as a template, so the `.etk` can be moved freely.
  - The program writes text content, barcode data, the QR code (new SVG plus its CRC32) and element positions into a copy of the template, and regenerates the preview thumbnail.
  - Fonts and sizes stay as in the template. Elements added in the program are not transferred, and elements deleted in the program stay in the `.btw`. A summary lists both after saving.
  - Verified in BarTender 2022: the edited file opens with the new data.

### Build
```bash
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --onefile --windowed --name ProjektantEtykiet --icon etykieta/ikona.ico --distpath dist --collect-data qtawesome etykieta/app.py
```
Tests: `python etykieta/selftest.py testout` (headless) and `python etykieta/test_uchwyty.py` (mouse handles). `python etykieta/acceptance.py testout` is a printer acceptance run; with `DRY=1` it writes to a file instead of printing.

---

## Polski

Program okienkowy do projektowania i drukowania etykiet, wzorowany na BarTenderze. Plik do uruchomienia to `dist/ProjektantEtykiet.exe` i nie wymaga instalacji.

### Elementy
- **Tekst** wielowierszowy. Dwuklik włącza edycję. Zaznacz słowo i użyj paska formatowania: czcionka, rozmiar, B/I/U, kolor, „biały na czarnym”. Bez edycji format dotyczy całego tekstu. Szerokość (zawijanie), wyrównanie i interlinię ustawia się w panelu.
- **Kody kreskowe**: EAN-13, EAN-8, UPC-A, EAN-14, Code 128, GS1-128, Code 39, ITF, Codabar. Ustawia się moduł X w mm, wysokość kresek i tekst pod kodem.
- **Kody 2D**: QR, Micro QR, DataMatrix, GS1 DataMatrix (dane jako `(01)05901234123457(10)PARTIA`), PDF417, Aztec.
- Linia, prostokąt (z zaokrągleniem), elipsa, obraz.
- **Zmiana rozmiaru myszką**: uchwyty przy zaznaczonym elemencie, przeciwna krawędź stoi w miejscu.
  - Ramka, elipsa i kod kreskowy mają 8 uchwytów, linia ma 2 końce.
  - W tekście narożniki skalują czcionkę, a boki zmieniają szerokość zawijania.
  - Kod 2D i obraz mają uchwyty tylko w narożnikach (stałe proporcje).
- Układ: wyrównywanie, kolejność, kopiuj/wklej/duplikuj, przesuwanie strzałkami (0,1 mm; z Shift 1 mm), przyciąganie do siatki, cofnij/ponów, blokada.

### Zmienne (w tekście i kodach)
`{DATA}`, `{DATA+365}` (np. data przydatności), `{CZAS}`, `{LICZNIK}`, `{LICZNIK:6}` (z zerami), `{NazwaKolumny}` z danych.

### Dane do druku (okno DRUKUJ → „Wczytaj dane”)
- **Plik Excel (.xlsx) lub CSV**: brany jest pierwszy arkusz, pierwszy wiersz to nazwy pól, każdy kolejny wiersz to jedna etykieta. Daty z Excela trafiają jako `dd.mm.rrrr`.
- **Baza danych**: łańcuch ODBC (np. `DSN=Produkcja;Trusted_Connection=yes`) albo ścieżka do pliku SQLite, plus zapytanie SQL. Kolumny wyniku stają się polami. Połączenie bez hasła zapisuje się w projekcie, a połączenie z hasłem nie.

### Pliki .etk
Projekt to tekst JSON z obrazami w środku. Dwuklik na pliku .etk otwiera program. Plik .exe przy każdym uruchomieniu sam ustawia to skojarzenie dla bieżącego konta Windows (bez uprawnień administratora), także po przeniesieniu pliku .exe. Ręcznie: menu Plik → „Otwieraj pliki .etk tym programem”.

### Import z BarTendera (.btw)
Plik → Otwórz przyjmuje też pliki .btw z BarTendera 2022, bez instalowania BarTendera.
- Odczytywane są: rozmiar etykiety, teksty (z pogrubionymi fragmentami, zawijaniem, wyrównaniem i punktem zaczepienia), kody EAN/UPC/Code 128/Code 39 oraz obrazy.
- Kod QR zapisany jako obraz staje się edytowalnym kodem QR.
- Po imporcie etykietę zapisuje się jako .etk obok. Pliku .btw program nie zmienia ani nie zapisuje.
- Format .btw jest zamknięty i został rozpoznany na przykładowych plikach. Czego program nie rozpozna, to pomija i wypisuje po imporcie.
- Czcionki drukarki (np. TSC Sans Serif) program zastępuje Arialem, który jest nieco szerszy. Warto sprawdzić długie tytuły.

### Zapis dla BarTendera (.btw)
Plik → „Zapisz dla BarTendera (.btw)…” tworzy nowy plik .btw z etykiety otwartej wcześniej z pliku .btw.
- Oryginalny plik jest wzorem i zostaje zapisany w projekcie .etk, więc projekt można przenosić bez pliku .btw.
- Do kopii wzoru trafiają: treści tekstów, dane kodów kreskowych, kod QR (nowy obraz SVG z sumą CRC32) i położenie elementów. Miniatura podglądu jest generowana od nowa.
- Czcionki i rozmiary zostają takie jak we wzorze. Elementy dodane w programie nie trafiają do .btw, a usunięte w programie zostają w .btw. Po zapisie program wypisuje jedne i drugie.
- Sprawdzone w BarTenderze 2022: zmieniony plik otwiera się z nowymi danymi.

### Druk (przycisk „Rozmiar i drukarka”, Ctrl+L)
- **TSC / TSPL** (główna drukarka: TSC MH341, 300 dpi):
  - Wysyłka prosto na USB, bez instalowania sterownika. Można też użyć kolejki Windows (RAW) lub TCP.
  - Kalibracja nośnika to GAPDETECT.
  - Przerwa między etykietami (domyślnie 3 mm) jest wysyłana zawsze. Bez niej drukarka nie synchronizuje się z przerwami.
  - Nawijanie to `SET REWIND ON` (wewnętrzny nawijak).
  - Zakładka „Rolka i nawijanie” i okno druku pokazują rysunek rolki z kierunkiem wysuwu.
  - Rolka z etykietami 70 × 50 wychodzącymi krótszym bokiem: kierunek na rolce to **90°**.
  - Przesunięcie w poprzek głowicy idzie poleceniem `SHIFT` (±25 mm), a wzdłuż wysuwu jest wliczane w obraz. Tylko tak nic nie jest ucinane.
  - Korekty marginesów ustawia się w zakładce „Marginesy i kalibracja”.
- **Zebra / ZPL**:
  - Wysyłka RAW do kolejki Windows albo przez TCP (port 9100).
  - Tryby wyjścia: odrywanie, odklejanie, nawijanie, obcinarka, aplikator.
  - Do ustawienia: rodzaj nośnika (przerwa / znacznik / ciągła), zaczernienie, prędkość, korekta odrywania, kalibracja nośnika.
- **Sterownik Windows** (Datamax E-4304 i inne): rysowanie wektorowe, rozmiar strony równy etykiecie.
- Kierunek na rolce (0/90/180/270°), lustro, przesunięcie X/Y w mm, kilka etykiet w poprzek rolki.
- Moduły kodów są wyrównywane do pełnych punktów głowicy. Dokumentacja wymiarowa podaje wartość efektywną.

### Eksport
- **Dokumentacja wymiarowa (PDF)**: rysunek w skali z wymiarami etykiety i numerami elementów oraz tabela (X, Y, szerokość, wysokość, obrót, czcionki, parametry kodów).
- PDF wektorowy, SVG, PNG w wybranej rozdzielczości.

### Budowanie .exe
```bash
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --onefile --windowed --name ProjektantEtykiet --icon etykieta/ikona.ico --distpath dist --collect-data qtawesome etykieta/app.py
```
Autotest: `python etykieta/selftest.py testout`. Uchwyty myszką: `python etykieta/test_uchwyty.py`. Test akceptacyjny drukarki: `python etykieta/acceptance.py testout` (z `DRY=1` zapisuje do pliku zamiast drukować).

### Historia zmian
Gałąź `main` to wersja zaakceptowana. Zmiany robi się na osobnej gałęzi i scala po teście.

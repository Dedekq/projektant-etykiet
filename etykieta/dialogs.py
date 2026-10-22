"""Okna dialogowe: ustawienia etykiety/drukarki i drukowanie."""
import csv
import datetime
import re

from PySide6.QtCore import QDate, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintPreviewDialog
from PySide6.QtWidgets import (QAbstractSpinBox, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

import output
import theme

MODES = {"T": "Odrywanie (tear-off)", "P": "Odklejanie (peel-off)", "R": "Nawijanie na nawijak (rewind)",
         "C": "Obcinarka (cutter)", "D": "Obcinarka – opóźnione cięcie", "A": "Aplikator"}
MEDIA = {"Y": "Etykiety z przerwą (gap)", "M": "Czarny znacznik (black mark)", "N": "Taśma ciągła"}
ORIENT = {0: "0° — bez obrotu", 90: "90° — obrót w prawo", 180: "180° — do góry nogami",
          270: "270° — obrót w lewo"}


def dspin(v, lo, hi, step=0.1, dec=2, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(v)
    w.setSuffix(suffix)
    return w


def ispin(v, lo, hi, suffix=""):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(int(v))
    w.setSuffix(suffix)
    return w


def combo(options, current):
    """options: dict wartość -> opis."""
    w = QComboBox()
    for k, v in options.items():
        w.addItem(v, k)
    i = w.findData(current)
    w.setCurrentIndex(max(0, i))
    return w


def connect_refresh(parent, fn):
    """Każda zmiana pola w oknie odświeża podgląd."""
    for w in parent.findChildren(QComboBox):
        w.currentIndexChanged.connect(fn)
    for w in parent.findChildren(QAbstractSpinBox):
        if hasattr(w, "valueChanged"):
            w.valueChanged.connect(fn)
    for w in parent.findChildren(QCheckBox):
        w.toggled.connect(fn)


class RollPreview(QWidget):
    """Rysunek rolki: etykiety ułożone tak, jak wyjdą z drukarki (wysuw w dół, dolna etykieta wychodzi pierwsza)."""

    def __init__(self, get_doc):
        super().__init__()
        self.get_doc = get_doc
        self.setMinimumSize(250, 360)
        self.img, self.doc = None, None

    def refresh(self, *_):
        self.doc = self.get_doc()
        pr = self.doc["print"]
        try:
            img = output.roll_image(self.doc, {"LICZNIK": 1}, dict(pr, dpi=150))  # mniej niż głowica = szybko
        except Exception:  # podgląd nie może blokować ustawień
            img = None
        # TSC (DIRECTION 1): góra obrazu wychodzi ostatnia; Zebra: góra obrazu wychodzi pierwsza
        if img is not None and pr["method"] == "zpl":
            img = img.mirrored(True, True)
        self.img = img
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#eef1f7"))
        if self.img is None:
            p.drawText(self.rect(), Qt.AlignCenter, "Brak podglądu")
            return
        pr, label = self.doc["print"], self.doc["label"]
        roll_w, roll_h = output.windows_page_size(pr, label)
        gap_mm = pr.get("gap") or 3.0
        head_h, foot_h = 34, 58
        avail_w, avail_h = self.width() - 70, self.height() - head_h - foot_h - 10
        k = min(avail_w / (roll_w + 6), avail_h / (roll_h * 2.4 + gap_mm * 2))  # px na mm: 2,4 etykiety
        liner_w = (roll_w + 6) * k
        x0 = (self.width() - 40 - liner_w) / 2
        # drukarka u góry
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#455a64"))
        p.drawRoundedRect(QRectF(x0 - 14, 4, liner_w + 28, head_h - 6), 6, 6)
        p.setPen(Qt.white)
        p.drawText(QRectF(x0 - 14, 4, liner_w + 28, head_h - 6), Qt.AlignCenter,
                   {"tspl": "TSC", "zpl": "Zebra"}.get(pr["method"], "Drukarka"))
        # podkład i etykiety
        top = head_h
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e7d9b9"))
        p.drawRect(QRectF(x0, top, liner_w, avail_h + 6))
        p.save()
        p.setClipRect(QRectF(x0, top, liner_w, avail_h + 6))
        y = top + 4
        for _ in range(3):
            r = QRectF(x0 + 3 * k, y, roll_w * k, roll_h * k)
            p.setPen(QPen(QColor("#90a4ae"), 1))
            p.setBrush(Qt.white)
            p.drawRoundedRect(r, label["radius"] * k, label["radius"] * k)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(r, self.img)
            y += (roll_h + gap_mm) * k
        p.restore()
        # strzałka wysuwu
        ax = x0 + liner_w + 22
        p.setPen(QPen(QColor(theme.RED), 3))
        p.drawLine(QPointF(ax, top + 10), QPointF(ax, top + avail_h - 10))
        p.setBrush(QColor(theme.RED))
        p.setPen(Qt.NoPen)
        tip = QPointF(ax, top + avail_h)
        p.drawPolygon(QPolygonF([tip, QPointF(ax - 8, tip.y() - 14), QPointF(ax + 8, tip.y() - 14)]))
        p.setPen(QColor("#263238"))
        p.drawText(QRectF(0, self.height() - foot_h, self.width(), foot_h), Qt.AlignCenter | Qt.TextWordWrap,
                   f"Wysuw w dół — dolna etykieta wychodzi pierwsza.\n"
                   f"W poprzek rolki: {roll_w:g} mm, długość: {roll_h:g} mm")


class SettingsDialog(QDialog):
    def __init__(self, label, pr, parent=None, doc=None):
        super().__init__(parent)
        self.doc = doc  # elementy etykiety do podglądu rolki
        self.setWindowTitle("Ustawienia etykiety i drukarki")
        self.setWindowIcon(theme.icon("cog", theme.GRAY))
        self.setMinimumWidth(760)
        self.pr = dict(pr)
        tabs = QTabWidget()
        printers = [p.printerName() for p in QPrinterInfo.availablePrinters()]

        t = QWidget(); f = QFormLayout(t)
        self.name = QLineEdit(label.get("name", "Etykieta"))
        self.w = dspin(label["w"], 5, 1000, 1, suffix=" mm")
        self.h = dspin(label["h"], 5, 2000, 1, suffix=" mm")
        self.radius = dspin(label["radius"], 0, 50, 0.5, suffix=" mm")
        f.addRow("Nazwa", self.name)
        f.addRow("Szerokość", self.w)
        f.addRow("Wysokość (długość)", self.h)
        f.addRow("Zaokrąglenie narożników", self.radius)
        tabs.addTab(t, theme.icon("label-outline", theme.BLUE), "Etykieta")

        t = QWidget(); f = QFormLayout(t)
        self.method = combo({"tspl": "TSC / TSPL (bezpośrednio)", "zpl": "Zebra / ZPL (bezpośrednio)",
                             "windows": "Sterownik Windows (np. Datamax)"}, pr["method"])
        self.target = combo({"usb": "USB — bezpośrednio, bez sterownika", "queue": "Kolejka Windows (RAW)",
                             "tcp": "Sieć TCP/IP"}, pr["zpl_target"])
        self.queue = QComboBox(); self.queue.addItems(printers); self.queue.setCurrentText(pr["queue"])
        self.host = QLineEdit(pr["host"])
        self.port = ispin(pr["port"], 1, 65535)
        self.winp = QComboBox(); self.winp.addItems(printers); self.winp.setCurrentText(pr["windows_printer"])
        self.dpi = combo({203: "203 dpi (8 pkt/mm)", 300: "300 dpi (12 pkt/mm)", 600: "600 dpi (24 pkt/mm)"},
                         pr["dpi"])
        f.addRow("Metoda druku", self.method)
        f.addRow("TSC / Zebra wysyłaj przez", self.target)
        f.addRow("Kolejka Windows", self.queue)
        f.addRow("Adres IP", self.host)
        f.addRow("Port", self.port)
        f.addRow("Drukarka Windows", self.winp)
        f.addRow("Rozdzielczość głowicy", self.dpi)
        cal = QPushButton(theme.icon("tape-measure", "white"), " Kalibruj nośnik (wykryj przerwę)")
        cal.clicked.connect(self.calibrate)
        f.addRow("", cal)
        tabs.addTab(t, theme.icon("printer", theme.RED), "Drukarka")

        t = QWidget(); tl = QHBoxLayout(t); fw = QWidget(); f = QFormLayout(fw); tl.addWidget(fw, 1)
        self.orient = combo(ORIENT, pr["orientation"])
        self.mirror = QCheckBox("Odbicie lustrzane"); self.mirror.setChecked(pr["mirror"])
        self.mode = combo(MODES, pr["mode"])
        self.media = combo(MEDIA, pr["media"])
        self.columns = ispin(pr["columns"], 1, 10)
        self.col_gap = dspin(pr["col_gap"], 0, 50, 0.5, suffix=" mm")
        self.gap = dspin(pr["gap"] or 3.0, 0.5, 30, 0.5, suffix=" mm")
        self.gap.setToolTip("Zmierz linijką odstęp między etykietami na rolce (zwykle 2–3 mm)")
        f.addRow("Kierunek na rolce", self.orient)
        f.addRow("", self.mirror)
        f.addRow("Tryb wyjścia (TSC/Zebra)", self.mode)
        f.addRow("Rodzaj nośnika (TSC/Zebra)", self.media)
        f.addRow("Przerwa między etykietami (TSC)", self.gap)
        f.addRow("Etykiet w poprzek rolki", self.columns)
        f.addRow("Odstęp między nimi", self.col_gap)
        self.roll = RollPreview(lambda: dict(self.doc or {}, label=self.values()[0], print=self.values()[1]))
        tl.addWidget(self.roll)
        tabs.addTab(t, theme.icon("rotate-3d-variant", theme.TEAL), "Rolka i nawijanie")

        t = QWidget(); f = QFormLayout(t)
        self.darkness = ispin(pr["darkness"], 0, 30)
        self.speed = ispin(pr["speed"], 1, 14, " cal/s")
        self.ox = dspin(pr["offset_x"], -50, 50, 0.1, suffix=" mm")
        self.oy = dspin(pr["offset_y"], -15, 15, 0.1, suffix=" mm")
        self.tear = ispin(pr["tear_off"], -120, 120, " pkt")
        f.addRow("Zaczernienie (0–30)", self.darkness)
        f.addRow("Prędkość", self.speed)
        f.addRow("Przesunięcie w prawo", self.ox)
        f.addRow("Przesunięcie w dół", self.oy)
        f.addRow("Korekta miejsca odrywania", self.tear)
        f.addRow(QLabel("Przesunięcia działają tak jak na ekranie (niezależnie od obrotu na rolce)\n"
                        "i we wszystkich drukarkach. Wartości ujemne = w lewo / w górę.\n"
                        "Dla sterownika Windows zaczernienie i prędkość ustawia się we właściwościach sterownika."))
        tabs.addTab(t, theme.icon("tune", theme.ORANGE), "Marginesy i kalibracja")

        connect_refresh(self, self.roll.refresh)
        self.roll.refresh()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(" Zapisz ustawienia")
        bb.button(QDialogButtonBox.Ok).setIcon(theme.icon("check-circle", "white"))
        bb.button(QDialogButtonBox.Cancel).setText(" Anuluj")
        bb.button(QDialogButtonBox.Cancel).setObjectName("secondary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(bb)

    def values(self):
        label = {"name": self.name.text(), "w": self.w.value(), "h": self.h.value(), "radius": self.radius.value()}
        pr = {**self.pr, "method": self.method.currentData(), "zpl_target": self.target.currentData(),
              "queue": self.queue.currentText(), "host": self.host.text(), "port": self.port.value(),
              "windows_printer": self.winp.currentText(), "dpi": self.dpi.currentData(),
              "orientation": self.orient.currentData(), "mirror": self.mirror.isChecked(),
              "mode": self.mode.currentData(), "media": self.media.currentData(),
              "columns": self.columns.value(), "col_gap": self.col_gap.value(), "gap": self.gap.value(),
              "darkness": self.darkness.value(), "speed": self.speed.value(),
              "offset_x": self.ox.value(), "offset_y": self.oy.value(), "tear_off": self.tear.value()}
        return label, pr

    def calibrate(self):
        _, pr = self.values()
        if pr["method"] == "windows":
            QMessageBox.information(self, "Kalibracja", "Przy sterowniku Windows kalibrację uruchamia się "
                                                        "z właściwości sterownika lub z panelu drukarki.")
            return
        cmd = (("BLINEDETECT\r\n" if pr["media"] == "M" else "GAPDETECT\r\n") if pr["method"] == "tspl"
               else f"^XA^MN{pr['media']}^XZ~JC")
        try:
            send_raw(pr, cmd)
            QMessageBox.information(self, "Kalibracja", "Wysłano polecenie kalibracji nośnika.")
        except Exception as ex:
            QMessageBox.critical(self, "Kalibracja", str(ex))


def send_raw(pr, data):
    """Wysyła gotowe polecenia TSPL/ZPL wybraną drogą."""
    if pr["zpl_target"] == "tcp":
        output.send_tcp(pr["host"], pr["port"], data)
    elif pr["zpl_target"] == "usb":
        output.send_usb(data)
    else:
        output.send_raw_to_queue(pr["queue"], data)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        return list(csv.DictReader(fh, dialect=dialect))


def cell_text(v):
    """Wartość z Excela / bazy jako tekst na etykietę: daty po polsku, 12.0 → 12."""
    if v is None:
        return ""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def read_xlsx(path):
    """Pierwszy arkusz; pierwszy wiersz = nazwy pól; puste wiersze pomijane."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        head = [str(h).strip() if h is not None else f"Kolumna{i + 1}" for i, h in enumerate(next(rows, ()))]
        return [dict(zip(head, map(cell_text, r))) for r in rows if any(v is not None for v in r)]
    finally:
        wb.close()


def read_data_file(path):
    return read_xlsx(path) if path.lower().endswith((".xlsx", ".xlsm")) else read_csv(path)


def read_sql(conn, query):
    """Wiersze z bazy: ścieżka do pliku .db/.sqlite = SQLite, inaczej łańcuch ODBC (DSN=…; albo DRIVER={…};…)."""
    from PySide6.QtSql import QSqlDatabase, QSqlQuery
    driver = "QSQLITE" if conn.strip().lower().endswith((".db", ".sqlite", ".sqlite3")) else "QODBC"
    name = "etykiety_dane"
    db = QSqlDatabase.addDatabase(driver, name)
    try:
        db.setDatabaseName(conn.strip())
        if not db.open():
            raise OSError("Nie można połączyć z bazą: " + db.lastError().text())
        q = QSqlQuery(db)
        if not q.exec(query):
            raise ValueError("Błąd zapytania: " + q.lastError().text())
        rec = q.record()
        names = [rec.fieldName(i) for i in range(rec.count())]
        rows = []
        while q.next():
            rows.append({n: cell_text(q.value(i)) for i, n in enumerate(names)})
        q.finish()
        del q
        db.close()
        return rows
    finally:
        del db
        QSqlDatabase.removeDatabase(name)


class DbDialog(QDialog):
    """Połączenie z bazą i zapytanie SQL; hasła nie są zapisywane w projekcie."""

    def __init__(self, conn, query, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dane z bazy danych")
        self.setWindowIcon(theme.icon("database", theme.TEAL))
        self.setMinimumWidth(620)
        f = QFormLayout(self)
        self.conn = QLineEdit(conn)
        self.conn.setPlaceholderText("DSN=Produkcja;Trusted_Connection=yes   albo   C:\\dane\\etykiety.db")
        self.query = QPlainTextEdit(query or "SELECT * FROM Produkty")
        self.query.setMaximumHeight(110)
        f.addRow("Połączenie (ODBC / plik SQLite)", self.conn)
        f.addRow("Zapytanie SQL", self.query)
        hint = QLabel("Każda kolumna wyniku to pole {nazwa_kolumny} na etykiecie, każdy wiersz to jedna etykieta. "
                      "Połączenie bez hasła (np. Trusted_Connection=yes) zostanie zapamiętane w projekcie.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(" Pobierz dane")
        bb.button(QDialogButtonBox.Ok).setIcon(theme.icon("database-arrow-down", "white"))
        bb.button(QDialogButtonBox.Cancel).setText(" Anuluj")
        bb.button(QDialogButtonBox.Cancel).setObjectName("secondary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


def has_password(conn):
    return bool(re.search(r"(^|;)\s*(pwd|password)\s*=", conn, re.I))


class PrintDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.rows = []
        pr = doc["print"]
        self.setWindowTitle("Drukuj etykiety")
        self.setWindowIcon(theme.icon("printer", theme.RED))
        f = QFormLayout()
        where = {"usb": "USB", "queue": pr["queue"], "tcp": pr["host"]}[pr["zpl_target"]]
        how = {"tspl": f"TSC → {where}", "zpl": f"Zebra → {where}"}.get(
            pr["method"], f"Sterownik Windows → {pr['windows_printer']}")
        f.addRow("Drukarka", QLabel(how + f"  ({pr['dpi']} dpi)"))
        self.copies = ispin(pr.get("copies", 1), 1, 100000)
        f.addRow("Ile kopii każdej etykiety", self.copies)
        # zmiana tylko dla tego wydruku: doc jest kopią, domyślne wartości zostają w ustawieniach projektu
        self.orient = combo(ORIENT, pr["orientation"])
        self.orient.currentIndexChanged.connect(lambda: pr.update(orientation=self.orient.currentData()))
        f.addRow("Kierunek na rolce", self.orient)
        self.mode = combo(MODES, pr["mode"])
        self.mode.currentIndexChanged.connect(lambda: pr.update(mode=self.mode.currentData()))
        self.mode.setEnabled(pr["method"] != "windows")
        self.mode.setToolTip("Tryb wyjścia działa na TSC i Zebrze; przy sterowniku Windows "
                             "ustawia się go we właściwościach sterownika")
        f.addRow("Tryb wyjścia (nawijanie)", self.mode)
        self.none = QRadioButton("Seria (licznik)"); self.none.setChecked(True)
        self.use_csv = QRadioButton("Dane z pliku lub bazy")
        row = QHBoxLayout(); row.addWidget(self.none); row.addWidget(self.use_csv)
        f.addRow("Źródło danych", row)
        self.count = ispin(1, 1, 100000)
        f.addRow("Ile różnych numerów", self.count)
        self.start = ispin(1, 0, 999999999)
        self.step = ispin(1, -1000, 1000)
        f.addRow("Numeracja od", self.start)
        f.addRow("Co ile (krok)", self.step)
        self.csv_btn = QPushButton(theme.icon("file-excel", "white"), " Plik Excel / CSV…")
        self.csv_btn.clicked.connect(self.pick_csv)
        self.db_btn = QPushButton(theme.icon("database", "white"), " Baza danych…")
        self.db_btn.clicked.connect(self.pick_db)
        src = QHBoxLayout(); src.addWidget(self.csv_btn); src.addWidget(self.db_btn)
        f.addRow("Wczytaj dane", src)
        self.csv_info = QLabel("—")
        self.csv_info.setWordWrap(True)
        f.addRow("", self.csv_info)
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True)
        f.addRow("Data na etykiecie", self.date)
        btns = QHBoxLayout()
        for text, fn, ico, name in (("Podgląd", self.preview, "eye-outline", "secondary"),
                                    ("Zapisz do pliku", self.save_zpl, "content-save-outline", "secondary"),
                                    ("Zamknij", self.reject, "close-circle", "secondary"),
                                    ("DRUKUJ", self.do_print, "printer", "danger")):
            b = QPushButton(theme.icon(ico, "white" if name == "danger" else theme.BLUE), " " + text)
            b.setObjectName(name)
            b.setIconSize(QSize(22, 22))
            b.clicked.connect(fn)
            btns.addWidget(b)
        self.roll = RollPreview(lambda: self.doc)
        self.orient.currentIndexChanged.connect(self.roll.refresh)  # po pr.update (podłączone wcześniej)
        self.roll.refresh()
        top = QHBoxLayout()
        top.addLayout(f, 1)
        top.addWidget(self.roll)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(btns)

    def pick_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Plik danych", "", "Excel lub CSV (*.xlsx *.xlsm *.csv *.txt)")
        if path:
            self._load(lambda: read_data_file(path), path.rsplit("/", 1)[-1])

    def pick_db(self):
        pr = self.doc["print"]
        dlg = DbDialog(pr.get("db_conn", ""), pr.get("db_query", ""), self)
        if not dlg.exec():
            return
        conn, query = dlg.conn.text(), dlg.query.toPlainText()
        if self._load(lambda: read_sql(conn, query), "baza danych"):
            # do projektu trafia tylko połączenie bez hasła
            pr.update(db_conn="" if has_password(conn) else conn, db_query=query)
            if self.parent() is not None and hasattr(self.parent(), "remember_db"):
                self.parent().remember_db(pr["db_conn"], query)

    def _load(self, read, source):
        try:
            self.rows = read()
        except Exception as ex:
            QMessageBox.critical(self, "Dane", f"Nie można wczytać danych:\n{ex}")
            return False
        cols = ", ".join("{" + c + "}" for c in (self.rows[0].keys() if self.rows else []))
        self.csv_info.setText(f"{source}: {len(self.rows)} wierszy; pola: {cols}")
        self.use_csv.setChecked(True)
        return True

    def records(self):
        d = self.date.date()
        now = datetime.datetime.combine(datetime.date(d.year(), d.month(), d.day()),
                                        datetime.datetime.now().time())
        base = self.rows if self.use_csv.isChecked() else [{}] * self.count.value()
        if self.use_csv.isChecked() and not base:
            raise ValueError("Wczytaj dane z pliku Excel / CSV albo z bazy danych")
        return [dict(r, LICZNIK=self.start.value() + i * self.step.value(), __now=now) for i, r in enumerate(base)]

    def preview(self):
        try:
            recs = self.records()
        except ValueError as ex:
            QMessageBox.warning(self, "Podgląd", str(ex))
            return
        pr = self.doc["print"]
        if pr["method"] == "windows":
            printer = self._printer()
            dlg = QPrintPreviewDialog(printer, self)
            dlg.paintRequested.connect(lambda p: output.paint_windows(p, self.doc, recs[:20], 1))
            dlg.exec()
            return
        img = (output.tspl_image(self.doc, recs[0], pr, output.windows_page_size(pr, self.doc["label"]))[0]
               if pr["method"] == "tspl" else output.roll_image(self.doc, recs[0], pr))
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Podgląd głowicy: {img.width()}×{img.height()} pkt (pierwsza etykieta)")
        lbl = QLabel()
        lbl.setPixmap(QPixmap.fromImage(img).scaled(img.width() * 2, img.height() * 2, Qt.KeepAspectRatio))
        sa = QScrollArea(); sa.setWidget(lbl)
        QVBoxLayout(dlg).addWidget(sa)
        dlg.resize(min(1200, img.width() * 2 + 40), min(900, img.height() * 2 + 40))
        dlg.exec()

    def _printer(self):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPrinterName(self.doc["print"]["windows_printer"])
        output.setup_printer(printer, self.doc)
        return printer

    def save_zpl(self):
        tspl = self.doc["print"]["method"] == "tspl"
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz zadanie druku", "",
                                              "TSPL (*.prn *.tspl)" if tspl else "ZPL (*.zpl *.prn)")
        if path:
            try:
                job = output.build_job(self.doc, self.records(), self.copies.value())
                with open(path, "wb") as fh:
                    fh.write(job if isinstance(job, bytes) else job.encode("ascii"))
            except Exception as ex:
                QMessageBox.critical(self, "Zapis", str(ex))

    def do_print(self):
        try:
            recs = self.records()
            pr = self.doc["print"]
            if pr["method"] != "windows":
                send_raw(pr, output.build_job(self.doc, recs, self.copies.value()))
            else:
                output.paint_windows(self._printer(), self.doc, recs, self.copies.value())
        except Exception as ex:
            QMessageBox.critical(self, "Druk", f"Drukowanie nie powiodło się:\n{ex}")
            return
        self.doc["print"]["copies"] = self.copies.value()
        self.accept()


PRESETS = [(100, 50), (100, 150), (100, 100), (70, 50), (58, 40), (50, 30), (60, 40), (40, 25), (105, 148)]


class NewLabelDialog(QDialog):
    """Proste okno „Nowa etykieta”: klik w rozmiar, klik w drukarkę, gotowe."""

    def __init__(self, label, pr, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nowa etykieta")
        self.setWindowIcon(theme.icon("file-plus", theme.BLUE))
        self.pr = dict(pr)
        lay = QVBoxLayout(self)
        title = QLabel("Jaki rozmiar ma etykieta?")
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        lay.addWidget(title)

        grid = QGridLayout()
        self.preset_btns = []
        # osobne grupy: autoExclusive łączyłby rozmiary z drukarkami (ten sam rodzic) i odznaczał drukarkę
        self.size_group = QButtonGroup(self)
        for n, (w, h) in enumerate(PRESETS):
            b = QToolButton()
            b.setObjectName("preset")
            b.setCheckable(True)
            self.size_group.addButton(b)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(theme.icon("label-outline" if w >= h else "label-variant-outline",
                                 [theme.BLUE, theme.GREEN, theme.ORANGE, theme.PURPLE, theme.TEAL][n % 5]))
            b.setIconSize(QSize(40, 40))
            b.setText(f"{w} × {h} mm")
            b.setMinimumSize(110, 80)
            b.setStyleSheet("QToolButton { background: white; border: 2px solid #d5dae5; border-radius: 10px; "
                            "font-weight: bold; } QToolButton:checked { border-color: #1e88e5; "
                            "background: #e3f2fd; } QToolButton:hover { border-color: #1e88e5; }")
            b.clicked.connect(lambda _=False, ww=w, hh=h: (self.w.setValue(ww), self.h.setValue(hh)))
            grid.addWidget(b, n // 5, n % 5)
            self.preset_btns.append((b, w, h))
        lay.addLayout(grid)

        own = QHBoxLayout()
        own.addWidget(QLabel("Albo wpisz własny:"))
        self.w = dspin(label["w"], 5, 1000, 1, 1, " mm")
        self.h = dspin(label["h"], 5, 2000, 1, 1, " mm")
        own.addWidget(QLabel("szerokość"))
        own.addWidget(self.w)
        own.addWidget(QLabel("wysokość"))
        own.addWidget(self.h)
        own.addStretch()
        lay.addLayout(own)
        self.w.valueChanged.connect(self._mark_preset)
        self.h.valueChanged.connect(self._mark_preset)
        self._mark_preset()

        title = QLabel("Na jakiej drukarce będziesz drukować?")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; margin-top: 10px;")
        lay.addWidget(title)
        row = QHBoxLayout()
        self.printer_btns = {}
        self.printer_group = QButtonGroup(self)
        for key, text, ico, col in (("tsc", "TSC MH341\n(USB)", "printer-pos", theme.RED),
                                    ("zebra", "Zebra\n(ZPL, sieć)", "printer-pos", theme.BLUE),
                                    ("datamax", "Datamax E-4304\n(sterownik)", "printer", theme.GREEN),
                                    ("other", "Inna drukarka\nWindows", "printer-outline", theme.ORANGE)):
            b = QToolButton()
            b.setCheckable(True)
            self.printer_group.addButton(b)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(theme.icon(ico, col))
            b.setIconSize(QSize(44, 44))
            b.setText(text)
            b.setMinimumSize(170, 100)
            b.setStyleSheet(self.preset_btns[0][0].styleSheet())
            row.addWidget(b)
            self.printer_btns[key] = b
        current = {"tspl": "tsc", "zpl": "zebra"}.get(pr["method"]) or (
            "datamax" if "datamax" in pr["windows_printer"].lower() else "other")
        self.printer_btns[current].setChecked(True)
        row.addStretch()
        lay.addLayout(row)
        tip = QLabel("Wszystko (nawijanie, marginesy, zaczernienie) zmienisz później przyciskiem "
                     "„Rozmiar i drukarka”.")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton(theme.icon("close-circle", theme.BLUE), " Anuluj")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        ok = QPushButton(theme.icon("check-circle", "white"), " Utwórz etykietę")
        ok.setIconSize(QSize(22, 22))
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _mark_preset(self, *_):
        """Podświetla kafelek pasujący do wpisanego rozmiaru albo żaden (własny rozmiar)."""
        self.size_group.setExclusive(False)
        for b, w, h in self.preset_btns:
            b.setChecked((w, h) == (self.w.value(), self.h.value()))
        self.size_group.setExclusive(True)

    def values(self):
        label = {"name": "Etykieta", "w": self.w.value(), "h": self.h.value(), "radius": 2.0}
        pr = dict(self.pr)
        choice = next(k for k, b in self.printer_btns.items() if b.isChecked())
        if choice == "tsc":
            # korekta zmierzona na TSC MH341 w tym zakładzie (22.10.2026); w innych — „Rozmiar i drukarka”
            pr.update(method="tspl", zpl_target="usb", dpi=300, offset_x=-1.25, offset_y=2.5)
        elif choice == "zebra":
            pr.update(method="zpl", zpl_target="queue", queue="Zebra", dpi=203)
        else:
            pr["method"] = "windows"
            if choice == "datamax":
                pr["windows_printer"] = "Datamax E-4304"
            else:
                pr["windows_printer"] = QPrinterInfo.defaultPrinterName()
        return label, pr

"""Projektant etykiet — okno główne."""
import json
import os
import sys

from PySide6.QtCore import QLibraryInfo, QPointF, QRectF, QSize, Qt, QTimer, QTranslator
from PySide6.QtGui import QAction, QColor, QFont, QImage, QKeySequence, QPainter, QPen, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDockWidget, QDoubleSpinBox,
                               QFileDialog, QFontComboBox, QFormLayout, QFrame, QGraphicsView, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

import btw_import
import output
import theme
from dialogs import NewLabelDialog, PrintDialog, SettingsDialog
from items import (BarcodeItem, Code2DItem, ImageItem, LabelItemMixin, LabelScene, ShapeItem, TextItem,
                   make_item, mm, to_mm)

APP = "Projektant etykiet"


class View(QGraphicsView):
    def __init__(self, scene, win):
        super().__init__(scene)
        self.win = win
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        # uchwyty i obrysy rysowane są nad elementami; pełne odświeżanie nie zostawia po nich śladów
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self._resize = None  # stan przeciągania uchwytu

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.win.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
        else:
            super().wheelEvent(e)

    HANDLE_PX = 10  # bok uchwytu na ekranie, niezależnie od powiększenia
    # kursor dla uchwytu; przy obrocie o 90°/270° osie się zamieniają
    CURSORS = [{"l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                "lt": Qt.SizeFDiagCursor, "rb": Qt.SizeFDiagCursor, "rt": Qt.SizeBDiagCursor, "lb": Qt.SizeBDiagCursor},
               {"l": Qt.SizeVerCursor, "r": Qt.SizeVerCursor, "t": Qt.SizeHorCursor, "b": Qt.SizeHorCursor,
                "lt": Qt.SizeBDiagCursor, "rb": Qt.SizeBDiagCursor, "rt": Qt.SizeFDiagCursor, "lb": Qt.SizeFDiagCursor}]

    def resize_target(self):
        sel = self.scene().selectedItems()
        if len(sel) == 1 and isinstance(sel[0], LabelItemMixin) and sel[0].resizable():
            return sel[0]
        return None

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        it = self.resize_target()
        if it is None:
            return
        hs = self.HANDLE_PX / max(1e-6, self.transform().m11())
        painter.setPen(QPen(Qt.white, 0))
        painter.setBrush(QColor(theme.BLUE))
        for p in it.handles().values():
            c = it.mapToScene(p)
            painter.drawRect(QRectF(c.x() - hs / 2, c.y() - hs / 2, hs, hs))

    def handle_at(self, view_pos):
        """Uchwyt zaznaczonego elementu pod kursorem albo None; narożniki mają pierwszeństwo."""
        it = self.resize_target()
        if it is None:
            return None
        hits = [(n, (self.mapFromScene(it.mapToScene(p)) - view_pos).manhattanLength())
                for n, p in it.handles().items()]
        hits = [(len(n) == 1, d, n) for n, d in hits if d <= self.HANDLE_PX + 2]
        return (it, min(hits)[2]) if hits else None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            hit = self.handle_at(e.position().toPoint())
            if hit:
                it, name = hit
                r = it.boundingRect()
                anchor = QPointF(r.right() if "l" in name else r.left(), r.bottom() if "t" in name else r.top())
                # stała przekształcenia z chwili kliknięcia: obrót elementu wokół środka zmienia się wraz z rozmiarem
                self._resize = dict(it=it, name=name, inv=it.sceneTransform().inverted()[0], rect=r,
                                    anchor=it.mapToScene(anchor), state=it.begin_resize())
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        p = self.mapToScene(e.position().toPoint())
        self.win.pos_label.setText(f"X {to_mm(p.x()):.1f} mm   Y {to_mm(p.y()):.1f} mm")
        if self._resize:
            self.drag_resize(p)
            return
        hit = self.handle_at(e.position().toPoint())
        if hit:
            self.viewport().setCursor(self.CURSORS[round(hit[0].rotation() / 90) % 2][hit[1]])
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(e)

    def drag_resize(self, scene_pos):
        s = self._resize
        it, name, r = s["it"], s["name"], s["rect"]
        local = s["inv"].map(scene_pos)
        snap = self.scene().snap_mm or 0.1
        q = lambda v: max(0.1, round(to_mm(v) / snap) * snap)
        w = q(r.right() - local.x() if "l" in name else local.x() - r.left())
        h = q(r.bottom() - local.y() if "t" in name else local.y() - r.top())
        it.resize_drag(s["state"], name, w, h)
        # przeciwna krawędź / narożnik zostaje w miejscu
        nr = it.boundingRect()
        anchor = it.mapToScene(QPointF(nr.right() if "l" in name else nr.left(),
                                       nr.bottom() if "t" in name else nr.top()))
        snap_mm, self.scene().snap_mm = self.scene().snap_mm, 0
        it.setPos(it.pos() + s["anchor"] - anchor)
        self.scene().snap_mm = snap_mm

    def mouseReleaseEvent(self, e):
        if self._resize:
            it = self._resize["it"]
            self._resize = None
            self.win.props.show_item(it)
            self.win.changed()
            return
        super().mouseReleaseEvent(e)
        self.win.changed()

    def contextMenuEvent(self, e):
        if self.scene().editing_item():
            return super().contextMenuEvent(e)  # menu edytora tekstu (kopiuj/wklej)
        self.win.context_menu(e.globalPos(), self.mapToScene(e.pos()))

    def keyPressEvent(self, e):
        sc = self.scene()
        if not sc.editing_item() and sc.selectedItems() and e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up,
                                                                         Qt.Key_Down):
            step = mm(1 if e.modifiers() & Qt.ShiftModifier else 0.1)
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(e.key(), 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(e.key(), 0)
            snap, sc.snap_mm = sc.snap_mm, 0  # strzałki precyzyjnie, bez przyciągania
            for it in sc.selectedItems():
                if not it.locked:
                    it.moveBy(dx, dy)
            sc.snap_mm = snap
            self.win.changed()
            return
        super().keyPressEvent(e)


HELP = (
    "<b>Jak zacząć?</b><br><br>"
    "1. Kliknij kolorowy przycisk po lewej (np. <b>Tekst</b> albo <b>Kod kreskowy</b>).<br>"
    "2. Przeciągnij element myszką w dobre miejsce.<br>"
    "3. Kliknij element — tutaj zmienisz jego treść i wymiary.<br>"
    "4. <b>Dwuklik na tekście</b> = pisanie. Zaznacz słowo i kliknij <b>B</b>, aby je pogrubić.<br>"
    "5. Gotowe? Kliknij czerwony przycisk <b>DRUKUJ</b>.<br><br>"
    "<b>Pola automatyczne</b> (wpisz w tekście lub kodzie):<br>"
    "{DATA} — dzisiejsza data<br>{DATA+365} — data za rok<br>{CZAS} — godzina<br>"
    "{LICZNIK:6} — numer kolejny 000001…<br>{nazwa kolumny} — dane z pliku CSV")


class PropertiesPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        head = QFrame()
        head.setObjectName("card")
        hl = QHBoxLayout(head)
        self.head_icon = QLabel()
        self.head_text = QLabel()
        hl.addWidget(self.head_icon)
        hl.addWidget(self.head_text, 1)
        lay.addWidget(head)
        body = QWidget()
        self.form = QFormLayout(body)
        self.form.setLabelAlignment(Qt.AlignRight)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(body)
        lay.addWidget(sa, 1)
        self.help = QLabel(HELP)
        self.help.setObjectName("hint")
        self.help.setWordWrap(True)
        lay.addWidget(self.help)
        row = QHBoxLayout()
        self.dup_btn = QPushButton(theme.icon("content-duplicate", theme.GREEN), " Duplikuj")
        self.dup_btn.setObjectName("secondary")
        self.dup_btn.clicked.connect(win.duplicate)
        self.del_btn = QPushButton(theme.icon("delete", "white"), " Usuń")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(win.delete)
        row.addWidget(self.dup_btn)
        row.addWidget(self.del_btn)
        lay.addLayout(row)
        self.item = None

    def show_item(self, item):
        self.item = item
        while self.form.rowCount():
            self.form.removeRow(0)
        n = len(self.win.selected())
        self.dup_btn.setVisible(bool(n))
        self.del_btn.setVisible(bool(n))
        self.help.setVisible(not n)
        if item is None:
            self.head_icon.setPixmap(theme.icon("selection" if n else "gesture-tap", theme.BLUE).pixmap(32, 32))
            self.head_text.setText(f"Zaznaczono: {n}" if n else "Nic nie zaznaczono")
            self.head_text.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {theme.BLUE};")
            return
        ico, col, name = theme.KIND_STYLE.get(item.kind, ("shape", theme.GRAY, item.kind))
        self.head_icon.setPixmap(theme.icon(ico, col).pixmap(32, 32))
        self.head_text.setText(name)
        self.head_text.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {col};")
        for key, label, kind, opts in item.all_props():
            if kind == "html":
                continue
            w = self._widget(key, kind, opts, item.get(key))
            self.form.addRow(label, w)

    def _widget(self, key, kind, opts, val):
        apply = lambda v, k=key: self.win.set_prop(self.item, k, v)
        if kind in ("mm", "float", "angle"):
            w = QDoubleSpinBox()
            lo, hi = opts or ((-360, 360) if kind == "angle" else (-1000, 1000))
            w.setRange(lo, hi)
            w.setDecimals(1 if kind == "angle" else 3 if key == "module" else 2)
            w.setSingleStep(90 if kind == "angle" else 0.1)
            w.setValue(val)
            w.setKeyboardTracking(False)
            w.valueChanged.connect(apply)
        elif kind == "int":
            w = QSpinBox()
            w.setRange(*opts)
            w.setValue(int(val))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(apply)
        elif kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(val))
            w.toggled.connect(apply)
        elif kind == "choice":
            w = QComboBox()
            w.addItems(opts)
            w.setCurrentText(val)
            w.currentTextChanged.connect(apply)
        elif kind == "text":
            w = QPlainTextEdit(val)
            w.setMaximumHeight(80)
            w.textChanged.connect(lambda: apply(w.toPlainText()))
        else:
            w = QLineEdit(str(val))
            w.editingFinished.connect(lambda: apply(w.text()))
        return w

    def refresh_position(self):
        if self.item is not None:
            for row in range(self.form.rowCount()):
                lbl = self.form.itemAt(row, QFormLayout.LabelRole)
                fld = self.form.itemAt(row, QFormLayout.FieldRole)
                if lbl and fld and lbl.widget().text() in ("X [mm]", "Y [mm]"):
                    w = fld.widget()
                    w.blockSignals(True)
                    w.setValue(self.item.get("x" if lbl.widget().text().startswith("X") else "y"))
                    w.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.path = None
        self.save_hint = None  # proponowana ścieżka zapisu etykiety bez pliku (np. po imporcie .btw)
        self.history, self.hpos = [], -1
        self.clipboard = []
        self.scene = LabelScene()
        self.view = View(self.scene, self)
        self.setCentralWidget(self.view)
        self.scene.selectionChanged.connect(self.selection_changed)
        # przy zamykaniu scena znika przed oknem i jej sygnał trafiłby do usuniętego obiektu
        QApplication.instance().aboutToQuit.connect(
            lambda: self.scene.selectionChanged.disconnect(self.selection_changed))
        self.scene.edited.connect(self.changed)
        self.props = PropertiesPanel(self)
        dock = QDockWidget("Właściwości elementu", self)
        dock.setWidget(self.props)
        dock.setMinimumWidth(330)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.pos_label = QLabel()
        self.statusBar().addPermanentWidget(self.pos_label)
        self._build_actions()
        self.resize(1300, 800)
        self.new_doc(ask=False)

    # ------------------------------------------------------------ akcje

    def act(self, text, fn, key=None, menu=None, bar=None, ico=None, color=theme.GRAY, tip=""):
        a = QAction(text, self)
        a.triggered.connect(fn)
        if ico:
            a.setIcon(theme.icon(ico, color))
        if key:
            a.setShortcut(QKeySequence(key))
        hint = tip or text.replace("\n", " ").rstrip("…")
        if key:
            hint += f"  ({a.shortcut().toString(QKeySequence.NativeText)})"
        a.setToolTip(hint)
        a.setStatusTip(tip or text)
        if menu:
            menu.addAction(a)
        if bar:
            bar.addAction(a)
        return a

    def toolbar(self, name, area=Qt.TopToolBarArea, size=28, under=True):
        tb = QToolBar(name)
        tb.setObjectName(name)
        tb.setMovable(False)
        tb.setIconSize(QSize(size, size))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon if under else Qt.ToolButtonIconOnly)
        self.addToolBar(area, tb)
        return tb

    def _build_actions(self):
        B, G, O, P, R, T, K = theme.BLUE, theme.GREEN, theme.ORANGE, theme.PURPLE, theme.RED, theme.TEAL, theme.PINK
        mb = self.menuBar()
        m = mb.addMenu("&Plik")
        em = mb.addMenu("&Edycja")

        # --- górny pasek: plik, cofnij, ustawienia, druk
        tb = self.toolbar("main")
        self.act("Nowa", self.new_doc, QKeySequence.New, m, tb, "file-plus", B, "Zacznij nową etykietę")
        self.act("Otwórz", self.open_doc, QKeySequence.Open, m, tb, "folder-open", O, "Otwórz zapisaną etykietę")
        self.act("Zapisz", self.save_doc, QKeySequence.Save, m, tb, "content-save", B, "Zapisz etykietę do pliku")
        self.act("Zapisz jako…", lambda: self.save_doc(True), QKeySequence.SaveAs, m, None, "content-save-edit", B)
        tb.addSeparator()
        self.act("Cofnij", self.undo, QKeySequence.Undo, em, tb, "undo", T, "Cofnij ostatnią zmianę")
        self.act("Ponów", self.redo, QKeySequence.Redo, em, tb, "redo", T, "Przywróć cofniętą zmianę")
        tb.addSeparator()
        m.addSeparator()
        self.act("Rozmiar i drukarka", self.settings, "Ctrl+L", m, tb, "cog", theme.GRAY,
                 "Rozmiar etykiety, wybór drukarki, nawijanie, marginesy i kalibracja")
        self.act("Wymiary PDF", self.export_dims, "Ctrl+Shift+D", m, tb, "ruler-square-compass", P,
                 "Utwórz dokumentację wymiarową (PDF z rysunkiem i tabelą wymiarów)")
        e = m.addMenu(theme.icon("file-export", G), "Eksportuj do pliku")
        self.act("PDF…", lambda: self.export("pdf"), None, e, None, "file-pdf-box", R)
        self.act("SVG…", lambda: self.export("svg"), None, e, None, "svg", O)
        self.act("PNG…", lambda: self.export("png"), None, e, None, "file-image", K)
        exp = QToolButton()
        exp.setMenu(e)
        exp.setPopupMode(QToolButton.InstantPopup)
        exp.setIcon(theme.icon("file-export", G))
        exp.setIconSize(QSize(28, 28))
        exp.setText("Eksport")
        exp.setToolTip("Zapisz etykietę jako PDF, SVG lub obraz PNG")
        exp.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.addWidget(exp)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        pa = self.act("DRUKUJ", self.print_dialog, QKeySequence.Print, m, tb, "printer", "white",
                      "Drukuj etykiety na wybranej drukarce")
        tb.widgetForAction(pa).setObjectName("print")
        m.addSeparator()
        self.act("Otwieraj pliki .etk tym programem", self.associate, None, m, None, "link-variant", theme.BLUE,
                 "Dwuklik na pliku .etk otworzy go w tym programie (tylko dla Twojego konta Windows)")
        m.addSeparator()
        self.act("Zakończ", self.close, None, m, None, "exit-to-app", theme.GRAY)

        # --- menu edycji
        em.addSeparator()
        self.act("Kopiuj", self.copy, QKeySequence.Copy, em, None, "content-copy", B)
        self.act("Wklej", self.paste, QKeySequence.Paste, em, None, "content-paste", B)
        self.act("Duplikuj", self.duplicate, "Ctrl+D", em, None, "content-duplicate", G)
        self.act("Usuń", self.delete, QKeySequence.Delete, em, None, "delete", R)
        self.act("Zaznacz wszystko", lambda: [i.setSelected(True) for i in self.scene.label_items()],
                 QKeySequence.SelectAll, em, None, "select-all", B)
        snap = self.act("Przyciągaj do siatki 0,5 mm", self.toggle_snap, None, em, None, "grid", T)
        snap.setCheckable(True)
        snap.setChecked(True)

        # --- lewy pasek: duże kolorowe przyciski wstawiania
        ib = self.toolbar("insert", Qt.LeftToolBarArea, 36)
        m = mb.addMenu("&Wstaw")
        for text, fn, key, ico, col, tip in (
                ("Tekst", lambda: self.add(TextItem()), "T", "format-text", B,
                 "Dodaj pole tekstowe. Dwuklik na tekście = pisanie i formatowanie"),
                ("Kod\nkreskowy", lambda: self.add(BarcodeItem()), "B", "barcode", G,
                 "Dodaj kod kreskowy (EAN-13, Code 128, GS1-128…)"),
                ("Kod QR", lambda: self.add(Code2DItem()), "Q", "qrcode", P, "Dodaj kod QR lub DataMatrix"),
                ("Data", lambda: self.add(TextItem("{DATA}")), None, "calendar", O,
                 "Dodaj dzisiejszą datę (wstawiana automatycznie przy druku)"),
                ("Licznik", lambda: self.add(TextItem("Nr {LICZNIK:6}")), None, "counter", T,
                 "Dodaj numer kolejny — zwiększa się z każdą drukowaną etykietą"),
                ("Linia", lambda: self.add(ShapeItem("line")), None, "vector-line", O, "Dodaj linię"),
                ("Ramka", lambda: self.add(ShapeItem("rect")), None, "rectangle-outline", O,
                 "Dodaj prostokąt / ramkę"),
                ("Elipsa", lambda: self.add(ShapeItem("ellipse")), None, "ellipse-outline", O, "Dodaj elipsę / koło"),
                ("Obraz", self.add_image, None, "image", K, "Dodaj logo lub obrazek z pliku")):
            self.act(text, fn, key, m, ib, ico, col, tip)
        v = m.addMenu(theme.icon("code-braces", T), "Zmienna")
        for name in ("{DATA}", "{DATA+365}", "{CZAS}", "{LICZNIK}", "{LICZNIK:6}"):
            self.act(name, lambda _=False, n=name: self.insert_var(n), None, v)
        self.act("Pole z CSV…", self.insert_csv_var, None, v, None, "table-arrow-down", G)

        # --- drugi rząd: formatowanie tekstu i układ
        self.addToolBarBreak()
        fb = self.toolbar("format", size=20, under=False)
        fb.addWidget(self._icon_label("format-font", B))
        self.font_box = QFontComboBox()
        self.font_box.setToolTip("Czcionka zaznaczonego tekstu")
        self.font_box.currentFontChanged.connect(lambda f: self.fmt(lambda c: c.setFontFamilies([f.family()])))
        fb.addWidget(self.font_box)
        self.size_box = QDoubleSpinBox()
        self.size_box.setRange(2, 400)
        self.size_box.setSingleStep(0.5)
        self.size_box.setSuffix(" pt")
        self.size_box.setValue(10)
        self.size_box.setKeyboardTracking(False)
        self.size_box.setToolTip("Wielkość czcionki")
        self.size_box.valueChanged.connect(lambda v: self.fmt(lambda c: c.setFontPointSize(v)))
        fb.addWidget(self.size_box)
        self.act("Pogrubienie", self.toggle_bold, "Ctrl+B", None, fb, "format-bold", B)
        self.act("Kursywa", self.toggle_italic, "Ctrl+I", None, fb, "format-italic", B)
        self.act("Podkreślenie", self.toggle_underline, "Ctrl+U", None, fb, "format-underline", B)
        self.act("Kolor tekstu", self.pick_color, None, None, fb, "format-color-text", R)
        self.act("Biały na czarnym (negatyw)", self.inverse, None, None, fb, "invert-colors", "#263238")
        fb.addSeparator()
        for text, val, ico in (("Tekst do lewej", "do lewej", "format-align-left"),
                               ("Tekst do środka", "do środka", "format-align-center"),
                               ("Tekst do prawej", "do prawej", "format-align-right")):
            self.act(text, lambda _=False, v=val: self.text_align(v), None, None, fb, ico, B)
        fb.addSeparator()
        m = mb.addMenu("&Układ")
        for text, how, ico in (("Do lewej krawędzi", "l", "align-horizontal-left"),
                               ("Wyśrodkuj w poziomie", "hc", "align-horizontal-center"),
                               ("Do prawej krawędzi", "r", "align-horizontal-right"),
                               ("Do górnej krawędzi", "t", "align-vertical-top"),
                               ("Wyśrodkuj w pionie", "vc", "align-vertical-center"),
                               ("Do dolnej krawędzi", "b", "align-vertical-bottom")):
            self.act(text, lambda _=False, h=how: self.align(h), None, m, fb, ico, G,
                     text + " etykiety (kilka zaznaczonych — względem siebie)")
        fb.addSeparator()
        m.addSeparator()
        self.act("Obróć o 90°", self.rotate90, "Ctrl+R", m, fb, "rotate-right", T)
        self.act("Na wierzch", lambda: self.zorder(True), "Ctrl+]", m, fb, "arrange-bring-to-front", O)
        self.act("Na spód", lambda: self.zorder(False), "Ctrl+[", m, fb, "arrange-send-to-back", O)
        self.act("Duplikuj", self.duplicate, None, None, fb, "content-duplicate", G)
        self.act("Usuń zaznaczone", self.delete, None, None, fb, "delete", R)
        m.addSeparator()
        self.act("Powiększ", lambda: self.zoom(1.25), QKeySequence.ZoomIn, m, None, "magnify-plus-outline", B)
        self.act("Pomniejsz", lambda: self.zoom(0.8), QKeySequence.ZoomOut, m, None, "magnify-minus-outline", B)
        self.act("Dopasuj do okna", self.fit, "Ctrl+0", m, None, "fit-to-screen-outline", B)
        self.act("Rozmiar rzeczywisty", self.real_size, "Ctrl+1", m, None, "ruler", B)

        # --- pasek stanu: podpowiedź i powiększenie
        sb = self.statusBar()
        for ico, tip, fn in (("magnify-minus-outline", "Pomniejsz", lambda: self.zoom(0.8)),
                             ("fit-to-screen-outline", "Dopasuj do okna", self.fit),
                             ("magnify-plus-outline", "Powiększ", lambda: self.zoom(1.25))):
            b = QToolButton()
            b.setIcon(theme.icon(ico, B))
            b.setIconSize(QSize(22, 22))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            sb.addPermanentWidget(b)
        sb.showMessage("Kliknij kolorowy przycisk po lewej, aby dodać element. "
                       "Dwuklik na tekście = pisanie. Prawy przycisk myszy = więcej opcji.")

    def _icon_label(self, ico, color):
        lbl = QLabel()
        lbl.setPixmap(theme.icon(ico, color).pixmap(20, 20))
        return lbl

    def context_menu(self, global_pos, scene_pos):
        it = next((i for i in self.scene.items(scene_pos) if isinstance(i, LabelItemMixin)), None)
        if it and not it.isSelected():
            self.scene.clearSelection()
            it.setSelected(True)
        m = QMenu(self)
        sel = self.selected()
        if sel:
            if len(sel) == 1 and isinstance(sel[0], TextItem):
                m.addAction(theme.icon("pencil", theme.BLUE), "Edytuj tekst", sel[0].start_edit)
            m.addAction(theme.icon("content-duplicate", theme.GREEN), "Duplikuj", self.duplicate)
            m.addAction(theme.icon("content-copy", theme.BLUE), "Kopiuj", self.copy)
            m.addAction(theme.icon("align-horizontal-center", theme.GREEN), "Wyśrodkuj w poziomie",
                        lambda: self.align("hc"))
            m.addAction(theme.icon("align-vertical-center", theme.GREEN), "Wyśrodkuj w pionie",
                        lambda: self.align("vc"))
            m.addAction(theme.icon("rotate-right", theme.TEAL), "Obróć o 90°", self.rotate90)
            m.addAction(theme.icon("arrange-bring-to-front", theme.ORANGE), "Na wierzch", lambda: self.zorder(True))
            m.addAction(theme.icon("arrange-send-to-back", theme.ORANGE), "Na spód", lambda: self.zorder(False))
            m.addSeparator()
            m.addAction(theme.icon("delete", theme.RED), "Usuń", self.delete)
        else:
            for text, ico, col, fn in (("Wstaw tekst", "format-text", theme.BLUE, lambda: self.add(TextItem())),
                                       ("Wstaw kod kreskowy", "barcode", theme.GREEN,
                                        lambda: self.add(BarcodeItem())),
                                       ("Wstaw kod QR", "qrcode", theme.PURPLE, lambda: self.add(Code2DItem()))):
                m.addAction(theme.icon(ico, col), text, fn)
            if self.clipboard:
                m.addAction(theme.icon("content-paste", theme.BLUE), "Wklej", self.paste)
            m.addSeparator()
            m.addAction(theme.icon("cog", theme.GRAY), "Rozmiar i drukarka…", self.settings)
        m.exec(global_pos)

    def rotate90(self):
        for i in self.selected():
            if not i.locked:
                i.setRotation((i.rotation() + 90) % 360)
        self.changed()
        self.selection_changed()

    def text_align(self, value):
        for i in self.selected():
            if isinstance(i, TextItem):
                i.set("align", value)
        self.changed()
        self.selection_changed()

    # ------------------------------------------------------------ dokument

    def doc(self):
        return self.scene.to_doc()

    def load(self, doc, keep_history=False):
        self.scene.load_doc(doc)
        if not keep_history:
            self.history, self.hpos = [json.dumps(doc)], 0
        self.update_title()
        self.selection_changed()

    def changed(self):
        s = json.dumps(self.doc())
        if self.history and s == self.history[self.hpos]:
            self.props.refresh_position()
            return
        self.history = self.history[: self.hpos + 1] + [s]
        self.hpos = len(self.history) - 1
        self.update_title()
        self.props.refresh_position()

    def dirty(self):
        return self.hpos != getattr(self, "saved_pos", 0) or self.history[self.hpos] != getattr(self, "saved", "")

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "bez nazwy"
        self.setWindowTitle(f"{name}{' *' if self.dirty() else ''} — {APP}")

    def undo(self):
        if self.hpos > 0:
            self.hpos -= 1
            self.load(json.loads(self.history[self.hpos]), keep_history=True)

    def redo(self):
        if self.hpos < len(self.history) - 1:
            self.hpos += 1
            self.load(json.loads(self.history[self.hpos]), keep_history=True)

    def confirm_discard(self):
        if not self.dirty():
            return True
        r = QMessageBox.question(self, APP, "Zapisać zmiany w etykiecie?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        return r == QMessageBox.Discard or (r == QMessageBox.Save and self.save_doc())

    def mark_saved(self):
        self.saved, self.saved_pos = self.history[self.hpos], self.hpos
        self.update_title()

    def new_doc(self, ask=True):
        if ask and not self.confirm_discard():
            return
        fresh = LabelScene()
        doc = fresh.to_doc()
        if ask:
            dlg = NewLabelDialog(doc["label"], doc["print"], self)
            if not dlg.exec():
                return
            doc["label"], doc["print"] = dlg.values()
        self.path = self.save_hint = None
        self.load(doc)
        self.mark_saved()
        QTimer.singleShot(0, self.fit)

    def open_doc(self, path=None):
        if not self.confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Otwórz etykietę", "",
                                                  "Etykiety (*.etk *.btw);;Etykieta (*.etk);;BarTender (*.btw)")
        if not path:
            return
        bartender = path.lower().endswith(".btw")
        try:
            if bartender:
                doc, warnings = btw_import.read_btw(path)
            else:
                with open(path, encoding="utf-8") as fh:
                    doc = json.load(fh)
        except Exception as ex:  # nieznany wariant .btw nie może zamknąć programu
            QMessageBox.critical(self, APP, f"Nie można otworzyć pliku:\n{ex}")
            return
        if bartender:
            # .btw tylko odczytujemy: zapis idzie do nowego pliku .etk obok
            self.path, self.save_hint = None, os.path.splitext(path)[0] + ".etk"
            self.load(doc)
            QTimer.singleShot(0, self.fit)
            QMessageBox.information(self, APP, "Zaimportowano etykietę BarTendera. Sprawdź ją i zapisz jako .etk "
                                    "(pliku .btw program nie zmienia)."
                                    + ("\n\nUwagi:\n• " + "\n• ".join(warnings) if warnings else ""))
            return
        self.path = path
        self.load(doc)
        self.mark_saved()
        QTimer.singleShot(0, self.fit)

    def save_doc(self, save_as=False):
        if save_as or not self.path:
            path, _ = QFileDialog.getSaveFileName(self, "Zapisz etykietę",
                                                  self.save_hint or self.scene.label.get("name", ""),
                                                  "Etykieta (*.etk)")
            if not path:
                return False
            self.path = path
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.doc(), fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)  # zapis atomowy: awaria nie zniszczy poprzedniej wersji
        except OSError as ex:
            QMessageBox.critical(self, APP, f"Nie zapisano pliku:\n{ex}")
            return False
        self.changed()
        self.mark_saved()
        return True

    def closeEvent(self, e):
        if self.confirm_discard():
            e.accept()
        else:
            e.ignore()

    # ------------------------------------------------------------ elementy

    def add(self, item):
        r = self.scene.label_rect()
        item.setPos(mm(2), mm(2))
        item.setZValue(self.scene.next_z())
        self.scene.addItem(item)
        self.scene.clearSelection()
        item.setSelected(True)
        if r.width() > item.boundingRect().width():
            item.setPos((r.width() - item.boundingRect().width()) / 2, (r.height() - item.boundingRect().height()) / 2)
        self.changed()

    def add_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Obraz", "", "Obrazy (*.png *.jpg *.jpeg *.bmp *.gif)")
        if path:
            img = QImage(path)
            if img.isNull():
                QMessageBox.warning(self, APP, "Nie można wczytać obrazu.")
                return
            self.add(ImageItem(img))

    def set_prop(self, item, key, value):
        if item.scene() is not self.scene:
            return
        item.set(key, value)
        self.changed()

    def selected(self):
        return [i for i in self.scene.selectedItems() if isinstance(i, LabelItemMixin)]

    def selection_changed(self):
        sel = self.selected()
        self.props.show_item(sel[0] if len(sel) == 1 else None)
        if len(sel) == 1 and isinstance(sel[0], TextItem):
            f = QTextCursor(sel[0].document()).charFormat().font()
            for w, v in ((self.font_box, f), (self.size_box, f.pointSizeF())):
                w.blockSignals(True)
                (w.setCurrentFont if w is self.font_box else w.setValue)(v)
                w.blockSignals(False)

    def delete(self):
        if self.scene.editing_item():
            return  # Delete w edytowanym tekście usuwa znak, nie element
        for i in self.selected():
            self.scene.removeItem(i)
        self.changed()

    def copy(self):
        if self.scene.editing_item():
            return  # kopiowanie fragmentu tekstu obsługuje sam edytor
        self.clipboard = [i.to_dict() for i in self.selected()]

    def paste(self):
        if self.scene.editing_item() or not self.clipboard:
            return
        self.scene.clearSelection()
        for d in self.clipboard:
            d = dict(d, x=d["x"] + 2, y=d["y"] + 2)
            it = make_item(d)
            it.setZValue(self.scene.next_z())
            self.scene.addItem(it)
            it.setSelected(True)
        self.clipboard = [i.to_dict() for i in self.selected()]
        self.changed()

    def duplicate(self):
        self.copy()
        self.paste()

    def toggle_snap(self, on):
        self.scene.snap_mm = 0.5 if on else 0

    def align(self, how):
        sel = [i for i in self.selected() if not i.locked]
        if not sel:
            return
        # jeden element — do etykiety; kilka — do ich wspólnego obrysu
        ref = self.scene.label_rect()
        if len(sel) > 1:
            ref = sel[0].sceneBoundingRect()
            for i in sel[1:]:
                ref = ref.united(i.sceneBoundingRect())
        for i in sel:
            b = i.sceneBoundingRect()
            dx = {"l": ref.left() - b.left(), "r": ref.right() - b.right(),
                  "hc": ref.center().x() - b.center().x()}.get(how, 0)
            dy = {"t": ref.top() - b.top(), "b": ref.bottom() - b.bottom(),
                  "vc": ref.center().y() - b.center().y()}.get(how, 0)
            snap, self.scene.snap_mm = self.scene.snap_mm, 0
            i.moveBy(dx, dy)
            self.scene.snap_mm = snap
        self.changed()

    def zorder(self, front):
        items = self.scene.label_items()
        sel = self.selected()
        rest = [i for i in items if i not in sel]
        order = rest + sel if front else sel + rest
        for z, i in enumerate(order):
            i.setZValue(z)
        self.changed()

    def insert_var(self, name):
        ed = self.scene.editing_item()
        if ed:
            ed.textCursor().insertText(name)
            return
        sel = self.selected()
        if len(sel) == 1 and isinstance(sel[0], (BarcodeItem, Code2DItem)):
            self.set_prop(sel[0], "data", sel[0].data + name)
            self.props.show_item(sel[0])
        elif len(sel) == 1 and isinstance(sel[0], TextItem):
            c = QTextCursor(sel[0].document())
            c.movePosition(QTextCursor.End)
            c.insertText(name)
            self.changed()
        else:
            QMessageBox.information(self, APP, "Zaznacz tekst lub kod, do którego wstawić zmienną.")

    def insert_csv_var(self):
        name, ok = QInputDialog.getText(self, "Pole z CSV", "Nazwa kolumny w pliku CSV:")
        if ok and name.strip():
            self.insert_var("{" + name.strip() + "}")

    # ------------------------------------------------------------ formatowanie tekstu

    def fmt(self, setter):
        """Stosuje format znakowy do zaznaczenia w edytowanym tekście albo do całych zaznaczonych tekstów."""
        cf = QTextCharFormat()
        setter(cf)
        ed = self.scene.editing_item()
        if ed:
            c = ed.textCursor()
            if not c.hasSelection():
                c.select(QTextCursor.WordUnderCursor)
            c.mergeCharFormat(cf)
            self.view.setFocus()
            ed.setFocus()
        else:
            for it in self.selected():
                if isinstance(it, TextItem):
                    c = QTextCursor(it.document())
                    c.select(QTextCursor.Document)
                    c.mergeCharFormat(cf)
        self.changed()

    def _cur_font(self):
        ed = self.scene.editing_item()
        if ed:
            return ed.textCursor().charFormat().font()
        t = next((i for i in self.selected() if isinstance(i, TextItem)), None)
        return QTextCursor(t.document()).charFormat().font() if t else QFont()

    def toggle_bold(self):
        on = not self._cur_font().bold()
        self.fmt(lambda c: c.setFontWeight(QFont.Bold if on else QFont.Normal))

    def toggle_italic(self):
        on = not self._cur_font().italic()
        self.fmt(lambda c: c.setFontItalic(on))

    def toggle_underline(self):
        on = not self._cur_font().underline()
        self.fmt(lambda c: c.setFontUnderline(on))

    def pick_color(self):
        col = QColorDialog.getColor(Qt.black, self)
        if col.isValid():
            self.fmt(lambda c: c.setForeground(col))

    def inverse(self):
        """Tekst biały na czarnym tle — typowe pole „negatyw” na etykietach termicznych."""
        self.fmt(lambda c: (c.setForeground(Qt.white), c.setBackground(Qt.black)))

    # ------------------------------------------------------------ widok

    def zoom(self, f):
        self.view.scale(f, f)

    def fit(self):
        self.view.fitInView(self.scene.label_rect().adjusted(-mm(5), -mm(5), mm(5), mm(5)), Qt.KeepAspectRatio)

    def real_size(self):
        self.view.resetTransform()
        k = self.logicalDpiX() / 96
        self.view.scale(k, k)

    # ------------------------------------------------------------ druk i eksport

    def settings(self):
        dlg = SettingsDialog(self.scene.label, self.scene.print, self, doc=self.doc())
        if dlg.exec():
            self.scene.label, self.scene.print = dlg.values()
            self.scene.update_rect()
            self.changed()
            self.fit()

    def print_dialog(self):
        self.scene.clearSelection()
        PrintDialog(self.doc(), self).exec()

    def associate(self):
        import fileassoc
        try:
            fileassoc.register()
        except OSError as ex:
            QMessageBox.critical(self, APP, f"Nie udało się ustawić otwierania plików .etk:\n{ex}")
            return
        QMessageBox.information(self, APP, "Gotowe. Dwuklik na pliku .etk otworzy go w tym programie.\n\n"
                                           "Jeśli przeniesiesz program w inne miejsce, kliknij tę opcję ponownie.")

    def remember_db(self, conn, query):
        """Okno druku działa na kopii projektu; połączenie z bazą (bez hasła) zapisujemy w samym projekcie."""
        self.scene.print.update(db_conn=conn, db_query=query)
        self.changed()

    def _save_path(self, title, filt, ext):
        base = os.path.splitext(self.path)[0] if self.path else self.scene.label.get("name", "etykieta")
        path, _ = QFileDialog.getSaveFileName(self, title, base + ext, filt)
        return path

    def export(self, kind):
        path = self._save_path("Eksport", {"pdf": "PDF (*.pdf)", "svg": "SVG (*.svg)", "png": "PNG (*.png)"}[kind],
                               "." + kind)
        if not path:
            return
        vars = {"LICZNIK": 1}
        try:
            if kind == "pdf":
                output.export_pdf(self.doc(), path, vars)
            elif kind == "svg":
                output.export_svg(self.doc(), path, vars)
            else:
                dpi, ok = QInputDialog.getInt(self, "PNG", "Rozdzielczość [dpi]:", 600, 72, 2400)
                if not ok:
                    return
                output.export_png(self.doc(), path, dpi, vars)
        except Exception as ex:
            QMessageBox.critical(self, APP, f"Eksport nie powiódł się:\n{ex}")
            return
        self.statusBar().showMessage("Zapisano " + path, 5000)

    def export_dims(self):
        path = self._save_path("Dokumentacja wymiarowa", "PDF (*.pdf)", " - wymiary.pdf")
        if not path:
            return
        try:
            output.export_dimensions(self.doc(), path, {"LICZNIK": 1}, os.environ.get("USERNAME", ""))
        except Exception as ex:
            QMessageBox.critical(self, APP, f"Nie utworzono dokumentacji:\n{ex}")
            return
        os.startfile(path)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    theme.apply_theme(app)
    tr = QTranslator(app)  # polskie przyciski w oknach Qt (Anuluj, Tak, Nie…)
    if tr.load("qtbase_pl", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(tr)
    app.setWindowIcon(theme.icon("label-outline", theme.BLUE))
    try:
        import fileassoc
        fileassoc.ensure_registered()  # dwuklik na .etk działa bez szukania opcji w menu
    except OSError:
        pass  # brak dostępu do rejestru nie może blokować programu; opcja w menu pokaże błąd
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith((".etk", ".btw")):  # .btw przez „Otwórz za pomocą”
        w.open_doc(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

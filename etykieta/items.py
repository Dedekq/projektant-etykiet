"""Elementy etykiety i scena. Jednostka sceny = piksel 96 DPI, więc czcionki w pt mają prawdziwy rozmiar."""
import base64
import datetime
import html
import re

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen,
                           QTextBlockFormat, QTextCursor, QTextOption)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsTextItem

import symbols

MM = 96 / 25.4  # jednostek sceny na 1 mm


def mm(v):
    return v * MM


def to_mm(v):
    return v / MM


# ---------------------------------------------------------------- zmienne

_VAR = re.compile(r"\{([^{}]+)\}")


def substitute(text, vars, escape=False):
    """{DATA}, {DATA+365}, {CZAS}, {LICZNIK}, {LICZNIK:6}, {kolumna CSV}. Nieznane zostają bez zmian."""
    if not vars:
        return text
    now = vars.get("__now") or datetime.datetime.now()

    def rep(m):
        name = m.group(1).strip()
        val = None
        d = re.fullmatch(r"DATA\s*([+-]\s*\d+)?", name, re.I)
        if d:
            days = int(d.group(1).replace(" ", "")) if d.group(1) else 0
            val = (now + datetime.timedelta(days=days)).strftime("%d.%m.%Y")
        elif name.upper() == "CZAS":
            val = now.strftime("%H:%M")
        elif re.fullmatch(r"LICZNIK(:\d+)?", name, re.I):
            width = int(name.split(":")[1]) if ":" in name else 0
            val = str(vars.get("LICZNIK", 1)).zfill(width)
        elif name in vars:
            val = str(vars[name])
        if val is None:
            return m.group(0)
        return html.escape(val) if escape else val

    return _VAR.sub(rep, text)


def sample(text):
    """Treść z przykładowymi wartościami zmiennych, do podglądu w edytorze."""
    return substitute(text, {"LICZNIK": 1}) if "{" in text else text


# ---------------------------------------------------------------- baza

class LabelItemMixin:
    kind = ""
    # (klucz, etykieta, typ, opcje); typy: mm, float, int, str, text, bool, choice, angle
    PROPS = []

    def _init_common(self):
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.locked = False

    def common_props(self):
        return [("x", "X [mm]", "mm", None), ("y", "Y [mm]", "mm", None),
                ("rotation", "Obrót [°]", "angle", None), ("locked", "Zablokuj", "bool", None)]

    def all_props(self):
        return self.common_props() + self.PROPS

    def get(self, key):
        if key == "x":
            return round(to_mm(self.pos().x()), 2)
        if key == "y":
            return round(to_mm(self.pos().y()), 2)
        if key == "rotation":
            return self.rotation()
        return getattr(self, key)

    def set(self, key, value):
        if key == "x":
            self.setPos(mm(value), self.pos().y())
        elif key == "y":
            self.setPos(self.pos().x(), mm(value))
        elif key == "rotation":
            self.setRotation(value)
        elif key == "locked":
            self.locked = value
            self.setFlag(QGraphicsItem.ItemIsMovable, not value)
        else:
            setattr(self, key, value)
            self.geometry_changed()

    def geometry_changed(self):
        self.prepareGeometryChange()
        self.setTransformOriginPoint(self.boundingRect().center())
        self.update()

    def to_dict(self):
        d = {"kind": self.kind}
        for key, *_ in self.all_props():
            d[key] = self.get(key)
        return d

    def load(self, d):
        for key, *_ in self.PROPS:
            if key in d:
                setattr(self, key, d[key])
        self.geometry_changed()
        self.setPos(mm(d.get("x", 0)), mm(d.get("y", 0)))
        self.setRotation(d.get("rotation", 0))
        self.set("locked", d.get("locked", False))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() and self.scene().snap_mm:
            s = mm(self.scene().snap_mm)
            return QPointF(round(value.x() / s) * s, round(value.y() / s) * s)
        return super().itemChange(change, value)

    def paint_selection(self, painter):
        if self.isSelected():
            painter.setPen(QPen(QColor(0, 120, 215), 0, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())

    def size_mm(self):
        r = self.boundingRect()
        return to_mm(r.width()), to_mm(r.height())

    def doc_details(self):
        """Opis do dokumentacji wymiarowej."""
        return ""

    def content(self):
        return ""


# ---------------------------------------------------------------- tekst

ALIGN = {"do lewej": Qt.AlignLeft, "do środka": Qt.AlignHCenter, "do prawej": Qt.AlignRight,
         "wyjustuj": Qt.AlignJustify}


class TextItem(LabelItemMixin, QGraphicsTextItem):
    kind = "text"
    PROPS = [("width", "Szerokość [mm] (0=auto)", "mm", None),
             ("align", "Wyrównanie", "choice", list(ALIGN)),
             ("line_height", "Interlinia [%]", "int", (50, 300)),
             ("html", "Treść", "html", None)]

    def __init__(self, text="Tekst"):
        super().__init__()
        self._init_common()
        self.document().setDocumentMargin(0)
        f = QFont("Arial", 10)
        f.setHintingPreference(QFont.PreferNoHinting)  # liniowe skalowanie przy druku
        self.document().setDefaultFont(f)
        self.setDefaultTextColor(Qt.black)  # nie z palety systemu (ciemny motyw dałby biały tekst)
        self.setPlainText(text)
        self.width = 0.0
        self.align = "do lewej"
        self.line_height = 100
        self.document().contentsChanged.connect(self._contents_changed)
        self.geometry_changed()

    # html to stan dokumentu, nie atrybut
    @property
    def html(self):
        return self.document().toHtml()

    @html.setter
    def html(self, value):
        self.document().setHtml(value)

    def _contents_changed(self):
        self.setTransformOriginPoint(self.boundingRect().center())

    def geometry_changed(self):
        self.setTextWidth(mm(self.width) if self.width > 0 else -1)
        opt = self.document().defaultTextOption()
        opt.setAlignment(ALIGN.get(self.align, Qt.AlignLeft))
        opt.setWrapMode(QTextOption.WordWrap)
        self.document().setDefaultTextOption(opt)
        cur = QTextCursor(self.document())
        cur.select(QTextCursor.Document)
        bf = QTextBlockFormat()
        bf.setAlignment(ALIGN.get(self.align, Qt.AlignLeft))
        bf.setLineHeight(self.line_height, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cur.mergeBlockFormat(bf)
        super().geometry_changed()

    def load(self, d):
        self.document().setHtml(d.get("html", ""))
        super().load({k: v for k, v in d.items() if k != "html"})

    def start_edit(self):
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)

    def mouseDoubleClickEvent(self, e):
        if not self.locked:
            self.start_edit()
        super().mouseDoubleClickEvent(e)

    # edycja nie kończy się przy utracie fokusu, bo pasek formatowania musi działać na zaznaczonym słowie;
    # kończy ją kliknięcie obok (LabelScene.mousePressEvent) albo Esc
    def stop_edit(self):
        if not self.editing():
            return
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        c = self.textCursor()
        c.clearSelection()
        self.setTextCursor(c)
        self.clearFocus()
        if self.scene():
            self.scene().edited.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.stop_edit()
            return
        super().keyPressEvent(e)

    def editing(self):
        return bool(self.textInteractionFlags() & Qt.TextEditable)

    def paint(self, painter, option, widget=None):
        from PySide6.QtWidgets import QStyle
        option.state &= ~QStyle.State_Selected  # własna ramka zaznaczenia
        super().paint(painter, option, widget)
        self.paint_selection(painter)

    def content(self):
        return self.toPlainText()

    def font_runs(self):
        """Unikalne formaty w tekście: (rodzina, pt, pogrubienie, kursywa, podkreślenie, przykład)."""
        runs = {}
        block = self.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.text().strip():
                    f = frag.charFormat().font()
                    key = (f.family(), round(f.pointSizeF(), 1), f.bold(), f.italic(), f.underline())
                    runs.setdefault(key, frag.text().strip()[:25])
                it += 1
            block = block.next()
        return [k + (v,) for k, v in runs.items()]

    def doc_details(self):
        out = []
        for fam, pt, b, i, u, sample in self.font_runs():
            f = QFont(fam)
            f.setPointSizeF(pt)
            f.setBold(b)
            fm = QFontMetricsF(f)  # metryki w px 96 DPI = jednostki sceny
            cap, xh = to_mm(fm.capHeight()), to_mm(fm.xHeight())
            style = "".join(s for s, on in (("B", b), ("I", i), ("U", u)) if on)
            out.append(f"{fam} {pt:g} pt{(' ' + style) if style else ''} "
                       f"(wersalik {cap:.2f} mm, x {xh:.2f} mm) — „{sample}”")
        return "\n".join(out)


# ---------------------------------------------------------------- kod kreskowy

class BarcodeItem(LabelItemMixin, QGraphicsItem):
    kind = "barcode"
    PROPS = [("symbology", "Symbolika", "choice", list(symbols.BARCODE_TYPES)),
             ("data", "Dane", "str", None),
             ("module", "Moduł X [mm]", "float", (0.1, 2.0)),
             ("bar_height", "Wysokość kresek [mm]", "mm", None),
             ("show_text", "Tekst pod kodem", "bool", None),
             ("font_size", "Czcionka tekstu [pt]", "float", (4, 30))]

    def __init__(self):
        super().__init__()
        self._init_common()
        self.symbology = "EAN-13"
        self.data = "590123412345"
        self.module = 0.33
        self.bar_height = 20.0
        self.show_text = True
        self.font_size = 8.0
        self.geometry_changed()

    def geometry_changed(self):
        try:
            self._pattern, self._text = symbols.barcode_modules(self.symbology, sample(self.data))
            self._error = None
        except Exception as ex:  # nieprawidłowe dane pokazujemy na etykiecie, zamiast wywracać aplikację
            self._pattern, self._text, self._error = "", "", str(ex)
        super().geometry_changed()

    def _font(self, painter=None):
        f = QFont("Arial")
        # pt liczone są wg DPI urządzenia; scena ma już skalę 96 DPI, więc kompensujemy (PDF 600 dpi itp.)
        dpi = painter.device().logicalDpiY() if painter and painter.device() else 96
        f.setPointSizeF(self.font_size * 96 / dpi)
        f.setHintingPreference(QFont.PreferNoHinting)
        return f

    def _ean(self):
        return self.symbology in ("EAN-13", "EAN-8") and "G" in self._pattern

    def _lead(self):
        # miejsce na pierwszą cyfrę EAN-13 przed kodem
        return mm(self.module) * 9 if self.show_text and self.symbology == "EAN-13" else 0

    def _text_h(self):
        return QFontMetricsF(self._font()).height() if self.show_text else 0

    def boundingRect(self):
        if self._error:
            return QRectF(0, 0, mm(40), mm(10))
        w = self._lead() + len(self._pattern) * mm(self.module)
        return QRectF(0, 0, w, mm(self.bar_height) + self._text_h())

    def paint(self, painter, option, widget=None):
        if self._error:
            painter.setPen(QPen(Qt.red, 0))
            painter.drawRect(self.boundingRect())
            painter.drawText(self.boundingRect(), Qt.TextWordWrap, "Błąd kodu: " + self._error)
            return
        m, h, x0 = mm(self.module), mm(self.bar_height), self._lead()
        th = self._text_h()
        ean = self._ean()
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.black)
        guards = []
        i, p = 0, self._pattern
        while i < len(p):
            if p[i] == "0":
                i += 1
                continue
            j = i
            while j < len(p) and p[j] == p[i]:
                j += 1
            ext = th * 0.5 if (p[i] == "G" and self.show_text) else 0
            painter.drawRect(QRectF(x0 + i * m, 0, (j - i) * m, h + ext))
            if p[i] == "G":
                guards.append((i, j))
            i = j
        if self.show_text:
            painter.setFont(self._font(painter))
            painter.setPen(Qt.black)
            txt = self._text
            if ean and len(guards) >= 6:
                txt = re.sub(r"\D", "", txt)  # pełny kod z python-barcode zawiera spacje i znak '>'
                starts = sorted(x0 + a * m for a, _ in guards)
                ends = sorted(x0 + b * m for _, b in guards)
                left = QRectF(ends[1], h, starts[2] - ends[1], th)
                right = QRectF(ends[3], h, starts[4] - ends[3], th)
                if self.symbology == "EAN-13":
                    painter.drawText(QRectF(0, h, x0 - m, th), Qt.AlignRight | Qt.AlignVCenter, txt[0])
                    a, b = txt[1:7], txt[7:]
                else:
                    a, b = txt[:4], txt[4:]
                painter.drawText(left, Qt.AlignCenter, a)
                painter.drawText(right, Qt.AlignCenter, b)
            else:
                painter.drawText(QRectF(x0, h, len(p) * m, th), Qt.AlignCenter, txt)
        self.paint_selection(painter)

    def content(self):
        return self.data

    def doc_details(self):
        if self._error:
            return "BŁĄD: " + self._error
        bars_w = len(self._pattern) * self.module
        s = (f"{self.symbology}, moduł X {self.module:.3f} mm, kreski {self.bar_height:.2f} mm, "
             f"szer. symbolu {bars_w:.2f} mm ({len(self._pattern)} modułów)")
        if self.symbology.startswith(("EAN", "UPC")):
            s += f", powiększenie {self.module / symbols.EAN_NOMINAL_MODULE_MM * 100:.0f}%"
        if self.show_text:
            s += f", tekst {self.font_size:g} pt"
        return s


# ---------------------------------------------------------------- kody 2D

CODE2D = ["QR", "Micro QR", "DataMatrix", "GS1 DataMatrix", "PDF417", "Aztec"]


class Code2DItem(LabelItemMixin, QGraphicsItem):
    kind = "code2d"
    PROPS = [("symbology", "Symbolika", "choice", CODE2D),
             ("data", "Dane", "text", None),
             ("module", "Moduł [mm]", "float", (0.1, 5.0)),
             ("ecc", "Korekcja błędów (QR)", "choice", ["L", "M", "Q", "H"]),
             ("quiet", "Margines [moduły]", "int", (0, 10))]

    def __init__(self):
        super().__init__()
        self._init_common()
        self.symbology = "QR"
        self.data = "https://example.com"
        self.module = 0.5
        self.ecc = "M"
        self.quiet = 0
        self.geometry_changed()

    def geometry_changed(self):
        try:
            data = sample(self.data)
            if self.symbology == "QR":
                self._m, self._ver = symbols.qr_matrix(data, self.ecc)
            elif self.symbology == "Micro QR":
                self._m, self._ver = symbols.qr_matrix(data, self.ecc if self.ecc != "H" else "Q", micro=True)
            elif self.symbology in ("PDF417", "Aztec"):
                self._m, self._ver = symbols.zxing_matrix(self.symbology, data)
            else:
                self._m, self._ver = symbols.datamatrix_matrix(data, gs1=self.symbology.startswith("GS1"))
            self._error = None
        except Exception as ex:
            self._m, self._ver, self._error = [], "", str(ex)
        super().geometry_changed()

    def boundingRect(self):
        if self._error:
            return QRectF(0, 0, mm(20), mm(20))
        q = self.quiet * 2
        return QRectF(0, 0, (len(self._m[0]) + q) * mm(self.module), (len(self._m) + q) * mm(self.module))

    def paint(self, painter, option, widget=None):
        if self._error:
            painter.setPen(QPen(Qt.red, 0))
            painter.drawRect(self.boundingRect())
            painter.drawText(self.boundingRect(), Qt.TextWordWrap, "Błąd: " + self._error)
            return
        m = mm(self.module)
        off = self.quiet * m
        path = QPainterPath()
        for y, row in enumerate(self._m):
            for x, on in enumerate(row):
                if on:
                    path.addRect(off + x * m, off + y * m, m, m)
        painter.fillPath(path.simplified(), Qt.black)  # bez szczelin między modułami
        self.paint_selection(painter)

    def content(self):
        return self.data

    def doc_details(self):
        if self._error:
            return "BŁĄD: " + self._error
        n = len(self._m[0])
        ver = self._ver if self.symbology in ("PDF417", "Aztec") else f"wersja {self._ver}"
        s = f"{self.symbology} {ver}, {n}×{len(self._m)} modułów, moduł {self.module:.3f} mm, " \
            f"symbol {n * self.module:.2f}×{len(self._m) * self.module:.2f} mm"
        if "QR" in self.symbology:
            s += f", korekcja {self.ecc}"
        return s


# ---------------------------------------------------------------- kształty

FILL = ["brak", "czarne", "białe"]


class ShapeItem(LabelItemMixin, QGraphicsItem):
    kind = "rect"
    PROPS = [("w", "Szerokość [mm]", "mm", None), ("h", "Wysokość [mm]", "mm", None),
             ("line", "Grubość linii [mm]", "float", (0, 20)),
             ("radius", "Zaokrąglenie [mm]", "float", (0, 100)),
             ("fill", "Wypełnienie", "choice", FILL)]

    def __init__(self, kind="rect"):
        super().__init__()
        self._init_common()
        self.kind = kind
        self.w, self.h, self.line, self.radius, self.fill = 20.0, 10.0, 0.3, 0.0, "brak"
        if kind == "line":
            self.w, self.h, self.fill = 30.0, 0.4, "czarne"
        self.geometry_changed()

    def all_props(self):
        props = self.common_props() + self.PROPS
        if self.kind == "line":
            return self.common_props() + [("w", "Długość [mm]", "mm", None), ("h", "Grubość [mm]", "mm", None)]
        if self.kind == "ellipse":
            return [p for p in props if p[0] != "radius"]
        return props

    def boundingRect(self):
        return QRectF(0, 0, mm(self.w), mm(self.h))

    def paint(self, painter, option, widget=None):
        r = self.boundingRect()
        if self.kind == "line":
            painter.fillRect(r, Qt.black)
        else:
            lw = mm(self.line)
            painter.setPen(QPen(Qt.black, lw, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin) if lw else Qt.NoPen)
            painter.setBrush({"czarne": Qt.black, "białe": Qt.white}.get(self.fill, Qt.NoBrush))
            inner = r.adjusted(lw / 2, lw / 2, -lw / 2, -lw / 2)  # obrys w środku wymiaru, jak w BarTenderze
            if self.kind == "ellipse":
                painter.drawEllipse(inner)
            else:
                painter.drawRoundedRect(inner, mm(self.radius), mm(self.radius))
        self.paint_selection(painter)

    def doc_details(self):
        if self.kind == "line":
            return f"linia {self.w:.2f} mm × grubość {self.h:.2f} mm"
        s = f"obrys {self.line:.2f} mm, wypełnienie: {self.fill}"
        if self.kind == "rect" and self.radius:
            s += f", promień {self.radius:.2f} mm"
        return s


# ---------------------------------------------------------------- obraz

class ImageItem(LabelItemMixin, QGraphicsItem):
    kind = "image"
    PROPS = [("w", "Szerokość [mm]", "mm", None), ("h", "Wysokość [mm]", "mm", None)]

    def __init__(self, image=None):
        super().__init__()
        self._init_common()
        self.png = ""
        self._img = QImage()
        self.w, self.h = 20.0, 20.0
        if image is not None:
            self.set_image(image)
        self.geometry_changed()

    def set_image(self, img):
        self._img = img
        buf = QBuffer()
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        self.png = base64.b64encode(bytes(buf.data())).decode()
        self.h = self.w * img.height() / max(1, img.width())

    def to_dict(self):
        return super().to_dict() | {"png": self.png}

    def load(self, d):
        self.png = d.get("png", "")
        self._img = QImage.fromData(QByteArray(base64.b64decode(self.png)), "PNG")
        super().load(d)

    def boundingRect(self):
        return QRectF(0, 0, mm(self.w), mm(self.h))

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(self.boundingRect(), self._img)
        self.paint_selection(painter)

    def doc_details(self):
        return f"grafika {self._img.width()}×{self._img.height()} px"


# ---------------------------------------------------------------- scena

KINDS = {"text": TextItem, "barcode": BarcodeItem, "code2d": Code2DItem, "image": ImageItem}

DEFAULT_PRINT = {
    "method": "tspl",         # tspl (TSC) | zpl (Zebra) | windows (sterownik)
    "zpl_target": "usb",      # sposób wysyłki TSPL/ZPL: usb | queue | tcp
    "queue": "Zebra", "host": "10.0.1.69", "port": 9100,
    "windows_printer": "Datamax E-4304",
    "dpi": 300,               # TSC MH341
    "gap": 3.0,               # przerwa / znacznik między etykietami [mm] (TSPL)
    "tspl_direction": 1,      # DIRECTION TSPL odpowiadające orientacji 0°
    "orientation": 0,         # obrót na rolce: 0/90/180/270
    "mirror": False,
    "mode": "T",              # T odrywanie, P odklejanie, R nawijanie, C obcinanie, D obcinanie opóźnione, A aplikator
    "media": "Y",             # Y przerwa, M znacznik, N ciągła
    "darkness": 15, "speed": 4,
    "offset_x": 0.0, "offset_y": 0.0,  # korekta pozycji druku [mm]
    "tear_off": 0,            # ~TA korekta pozycji odrywania [punkty]
    "columns": 1, "col_gap": 3.0,      # etykiety obok siebie na rolce
    "copies": 1,
}


def make_item(d):
    k = d["kind"]
    item = ShapeItem(k) if k in ("rect", "ellipse", "line") else KINDS[k]()
    item.load(d)
    return item


class LabelScene(QGraphicsScene):
    edited = Signal()

    def __init__(self, preview=False):
        super().__init__()
        self.preview = preview  # True = render do druku: bez siatki i obrysu
        self.label = {"w": 100.0, "h": 50.0, "radius": 2.0, "name": "Etykieta"}
        self.print = dict(DEFAULT_PRINT)
        self.snap_mm = 0.0 if preview else 0.5
        self.grid = not preview
        self.update_rect()

    def editing_item(self):
        return next((i for i in self.items() if isinstance(i, TextItem) and i.editing()), None)

    def mousePressEvent(self, e):
        ed = self.editing_item()
        if ed and ed not in self.items(e.scenePos()):
            ed.stop_edit()
        super().mousePressEvent(e)

    def label_rect(self):
        return QRectF(0, 0, mm(self.label["w"]), mm(self.label["h"]))

    def update_rect(self):
        r = self.label_rect()
        pad = 0 if self.preview else mm(15)
        self.setSceneRect(r.adjusted(-pad, -pad, pad, pad))
        self.update()

    def drawBackground(self, painter, rect):
        r = self.label_rect()
        rad = mm(self.label["radius"])
        if self.preview:
            painter.fillRect(r, Qt.white)
            return
        painter.fillRect(rect, QColor(200, 200, 205))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawRoundedRect(r.translated(mm(0.7), mm(0.7)), rad, rad)
        painter.setBrush(Qt.white)
        painter.drawRoundedRect(r, rad, rad)
        if self.grid:
            step = mm(5)
            painter.setPen(QPen(QColor(225, 228, 235), 0))
            x = step
            while x < r.width():
                painter.drawLine(QPointF(x, 0), QPointF(x, r.height()))
                x += step
            y = step
            while y < r.height():
                painter.drawLine(QPointF(0, y), QPointF(r.width(), y))
                y += step

    def drawForeground(self, painter, rect):
        if not self.preview:
            painter.setPen(QPen(QColor(120, 120, 130), 0))
            painter.setBrush(Qt.NoBrush)
            rad = mm(self.label["radius"])
            painter.drawRoundedRect(self.label_rect(), rad, rad)

    def label_items(self):
        # kolejność rysowania = kolejność zapisu
        return sorted((i for i in self.items() if isinstance(i, LabelItemMixin)), key=lambda i: i.zValue())

    def to_doc(self):
        items = []
        for i in self.label_items():
            items.append(i.to_dict())
        return {"version": 1, "label": dict(self.label), "print": dict(self.print), "items": items}

    def load_doc(self, doc, vars=None):
        self.clear()
        self.label = {**self.label, **doc.get("label", {})}
        self.print = {**DEFAULT_PRINT, **doc.get("print", {})}
        for z, d in enumerate(doc.get("items", [])):
            if vars is not None:
                d = dict(d)
                for key in ("data", "html"):
                    if key in d:
                        d[key] = substitute(d[key], vars, escape=(key == "html"))
            item = make_item(d)
            item.setZValue(z)
            if self.preview:
                item.setFlags(QGraphicsItem.GraphicsItemFlag(0))
            self.addItem(item)
        self.update_rect()

    def next_z(self):
        return max((i.zValue() for i in self.label_items()), default=-1) + 1

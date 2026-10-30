"""Etykiety BarTender (.btw) bez BarTendera: import i zapis na podstawie wzoru.

Format jest zamknięty; rozpoznany na plikach BarTender 2022 (archiwum MFC w strumieniu zlib):
pozycje w milsach (1/1000 cala), 9 punktów zaczepienia, teksty jako fragmenty z czcionkami LOGFONT,
kody EAN, obrazy (SVG/PNG/BMP/JPG). Czego nie rozpoznajemy, pomijamy i zgłaszamy w ostrzeżeniach.

Zapis: nowego pliku od zera nie tworzymy. Import zapamiętuje cały plik jako wzór (doc["btw_template"])
i przy każdym elemencie odnośnik do jego obiektu; zapis podmienia we wzorze treści, dane kodów, kod QR
i pozycje (sprawdzone: BarTender otwiera tak zmieniony plik). Elementy dodane w programie nie trafiają do .btw."""
import base64
import copy
import itertools
import os
import re
import struct
import zlib

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QTextCharFormat, QTextCursor

import items
import symbols

MIL = 0.0254  # mm

BARCODES = {"BcEAN13Data": "EAN-13", "BcEAN8Data": "EAN-8", "BcUPCAData": "UPC-A", "BcCode128Data": "Code 128",
            "BcCode39Data": "Code 39", "BcEAN14Data": "EAN-14", "BcITF14Data": "ITF", "BcCodabarData": "Codabar"}
# klasy archiwum, które nie są elementami projektu (tło, formularz, ustawienia)
IGNORED = {"BackgroundRFIDData", "BackgroundData", "DialogData", "ScreenDs", "ScriptEvent", "FormatData",
           "NumberFormatData", "ImageHandle", "ImageHandleRef"}

_TOK = re.compile(rb"\xff\xff[\x00-\x20]\x00([\x02-\x40])\x00|([\x01-\x7f])\x80")
# bajt \x01 po pierwszym pustym CString jest w archiwum 2022 (113002), nie ma go w zgodnym z BT 10.1 (88634)
_HDR = re.compile(rb"\xff\xfe\xff\x00\x01?\xff\xfe\xff\x00\x00\x00\x00\x00\xff\xfe\xff\x00\x00\x01([\s\S])\x00{21}\xff\xfe\xff")
# shortcut: wartość źródła danych rozpoznajemy po domyślnej masce „(???) ???-????” przed nią — działa na
# wszystkich znanych plikach; inna maska (zmieniona w BarTenderze) = brak treści i ostrzeżenie
_VAL = re.compile(re.escape("(???) ???-????".encode("utf-16-le")) + rb"\xff\xfe\xff\x00\xff\xff\xff\xff\xff\xfe\xff")
_FACE = re.compile(rb"[A-Z]\x00(?:[A-Za-z0-9 \-]\x00){1,30}\x00\x00")
# blok liczb (float) za rozmiarem pola tekstu; pierwsza bywa różna (10,0 / 100,0)
_SIZE = re.compile(rb"(?<=\x01\x00\x00\x00\x01\x00\x00\x00)[\s\S]{4}\x00\x00\x7a\x44\x00\x00\xa0\x42")
# format akapitu za wartością: FF×8, zawijanie (0/1), wyrównanie (0 lewo, 1 środek, 2 prawo), ?, szerokość zawijania
_PARA = re.compile(rb"\xff{8}([\x00\x01])\x00\x00\x00([\x00-\x03])\x00\x00\x00[\s\S]{4}([\s\S]{4})")


def _cstr(d, i):
    """CString MFC (UTF-16) zaczynający się od długości w d[i] -> (tekst, koniec)."""
    n = d[i]
    i += 1
    if n == 0xFF:
        n = int.from_bytes(d[i:i + 2], "little")
        i += 2
    return d[i:i + 2 * n].decode("utf-16-le", "replace"), i + 2 * n


def _i32(d, i):
    return struct.unpack_from("<i", d, i)[0]


def _cs(text):
    """Tekst -> CString MFC (UTF-16, długość 1 bajt albo FF + 2 bajty)."""
    b = text.encode("utf-16-le")
    n = len(b) // 2
    return b"\xff\xfe\xff" + (bytes([n]) if n < 255 else b"\xff" + n.to_bytes(2, "little")) + b


def _stream(raw):
    """(początek, treść) strumienia dokumentu: zlib od CString „BarTender” do końca pliku."""
    for m in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", raw):
        try:
            out = zlib.decompressobj().decompress(raw[m.start():])
        except zlib.error:
            continue
        if out.startswith(b"\xff\xfe\xff\tB\x00a\x00r\x00T\x00e\x00n\x00d\x00e\x00r\x00"):
            return m.start(), out
    raise ValueError("To nie jest plik BarTendera (.btw) albo ta wersja formatu nie jest obsługiwana.")


def document_stream(raw):
    return _stream(raw)[1]


def _class_ends(d):
    """Indeksy klas MFC: nowa klasa (FFFF, schemat, nazwa) i odwołanie (0x8000|indeks) -> {koniec znacznika: klasa}."""
    entries, ends, pos = [None], {}, 0
    while m := _TOK.search(d, pos):
        if m.group(1):
            n = m.group(1)[0]
            name = d[m.end():m.end() + n]
            if re.fullmatch(rb"[A-Za-z][A-Za-z0-9_]+", name):
                entries += [("class", name.decode()), ("obj", name.decode())]
                ends[m.end() + n] = name.decode()
                pos = m.end() + n
            else:
                pos = m.start() + 1
            continue
        v = m.group(2)[0]
        if v < len(entries) and entries[v] and entries[v][0] == "class":
            entries.append(("obj", entries[v][1]))
            ends[m.end()] = entries[v][1]
        pos = m.end()
    return ends


def _objects(d):
    """Obiekty projektu: klasa, nazwa, x/y [mils], zaczepienie (0..8: wiersz*3+kolumna), zakres bajtów."""
    ends = _class_ends(d)
    found = []
    for m in _HDR.finditer(d):
        name, after = _cstr(d, m.end())
        h = m.start()
        for n in range(600):  # przed nagłówkiem CString dowolnej długości, a przed nim x, y
            q = h - 4 - 2 * n if n < 255 else h - 6 - 2 * n
            if d[q:q + 3] == b"\xff\xfe\xff" and (d[q + 3] == n if n < 255 else
                                                  d[q + 3] == 0xFF and int.from_bytes(d[q + 4:q + 6], "little") == n):
                break
        else:
            continue
        cls = ends.get(q - 20)
        if cls:
            found.append({"cls": cls, "name": name, "x": _i32(d, q - 20), "y": _i32(d, q - 16),
                          "anchor": m.group(1)[0], "pos": q - 20, "end": after})
    for k, o in enumerate(found):
        o["stop"] = found[k + 1]["pos"] if k + 1 < len(found) else len(d)
    return found


def _logfont(d, s):
    """LOGFONTW od s -> (rodzina, pt, pogrubienie, kursywa, podkreślenie) albo None."""
    if s < 0 or s + 92 > len(d):
        return None
    h, _w, _e, _o, weight = struct.unpack_from("<5i", d, s)
    face = d[s + 28:s + 92].decode("utf-16-le", "replace").split("\x00")[0]
    if not (0 < abs(h) < 5000 and weight % 100 == 0 and weight <= 900 and face[:1].isalpha()):
        return None
    return face, abs(h) / 20, weight >= 600, bool(d[s + 20]), bool(d[s + 21])  # wysokość w 1/20 pt


def _fonts(d, a, b):
    out = []
    for m in _FACE.finditer(d, a, b):
        f = _logfont(d, m.start() - 28)
        if f:
            out.append((m.start() - 28, f))
    return out


def _values(d, a, b):
    """Wartości źródeł danych w obiekcie: (tekst, koniec, własna czcionka albo None, początek CString)."""
    out = []
    for m in _VAL.finditer(d, a, b):
        text, e = _cstr(d, m.end())
        own = _logfont(d, e + 13) if d[e + 11] == 1 else None
        out.append((text, e, own, m.end() - 3))
    return out


def _text_box(d, a, b):
    """Blok rozmiaru pola tekstu: (stały rozmiar, szerokość, wysokość) [mils] albo None."""
    hits = [m.start() for m in _SIZE.finditer(d, a, b)]
    if not hits:
        return None
    i = hits[-1]
    return d[i - 25] == 1, _i32(d, i - 24), _i32(d, i - 20)


def _fixed_box(d, o, vals):
    """(stały rozmiar, szerokość, wysokość [mm]) pola tekstu."""
    box = _text_box(d, vals[-1][1], o["stop"]) or (False, 0, 0)
    return box[0] and box[1] > 0 and box[2] > 0, box[1] * MIL, box[2] * MIL


def _shown(vals, fixed):
    """Wartości tak, jak widać je w polu (\\n = nowy wiersz). Końcowe \\r BarTender pomija w polu o stałym
    rozmiarze (jeden wiersz) i na końcu tekstu."""
    return [(v[0].rstrip("\r") if fixed or n == len(vals) - 1 else v[0]).replace("\r", "\n")
            for n, v in enumerate(vals)]


class Importer:
    def __init__(self, raw):
        self.raw = raw
        self.d = document_stream(raw)
        self.warnings = []
        m = re.search(rb"<TemplateSize>\s*([\d.,]+)\s*x\s*([\d.,]+)\s*(mm|cm|in)?\s*</TemplateSize>", raw)
        if not m:
            raise ValueError("Brak rozmiaru etykiety w pliku .btw.")
        k = {b"cm": 10, b"in": 25.4}.get(m.group(3), 1)
        self.w, self.h = (float(v.replace(b",", b".")) * k for v in m.groups()[:2])
        p = re.search(rb"<Printer>([^<]*)</Printer>", raw)
        self.printer = p.group(1).decode("utf-8", "replace") if p else ""
        self._families = set(QFontDatabase.families())
        self._replaced = set()

    def warn(self, s):
        if s not in self.warnings:
            self.warnings.append(s)

    def family(self, face):
        if face in self._families:
            return face
        self._replaced.add(face)  # czcionki drukarki (np. TSC Sans Serif) nie ma w Windows
        return "Arial"

    @staticmethod
    def place(o, w, h):
        """Lewy górny róg [mm] z punktu zaczepienia BarTendera i rozmiaru obiektu [mm]."""
        col, row = o["anchor"] % 3, min(2, o["anchor"] // 3)
        return o["x"] * MIL - col * w / 2, o["y"] * MIL - row * h / 2

    # ------------------------------------------------------------ tekst
    def text(self, o):
        d = self.d
        vals = _values(d, o["end"], o["stop"])
        if not vals:
            self.warn(f"„{o['name']}”: nie odczytano treści — pominięto.")
            return None
        fonts = _fonts(d, o["end"], o["stop"])
        default = fonts[-1][1] if fonts else ("Arial", 10.0, False, False, False)
        fixed, bw, bh = _fixed_box(d, o, vals)
        p = _PARA.search(d, vals[-1][1], o["stop"])  # jeden format akapitu, za ostatnią wartością
        wrap, align, wrap_w = (p.group(1)[0], p.group(2)[0], _i32(p.group(3), 0)) if p else (0, 0, 0)
        item = items.TextItem("")
        doc = item.document()
        cur = QTextCursor(doc)
        replaced = False
        for v, text in zip(vals, _shown(vals, fixed)):
            fam, pt, bold, italic, under = v[2] or default
            replaced |= fam not in self._families
            f = QTextCharFormat()
            f.setFontFamilies([self.family(fam)])
            f.setFontPointSize(pt)
            f.setFontWeight(QFont.Bold if bold else QFont.Normal)
            f.setFontItalic(italic)
            f.setFontUnderline(under)
            for k, line in enumerate(text.split("\n")):
                if k:
                    cur.insertBlock()
                cur.insertText(line, f)
        item.align = {1: "do środka", 2: "do prawej", 3: "wyjustuj"}.get(align, "do lewej")
        item.width = 0.0
        item.geometry_changed()
        if fixed:
            # pole o stałym rozmiarze: BarTender dopasowuje czcionkę do ramki (zgodność z podglądem ±5%)
            w, h = item.size_mm()
            items.scale_doc_fonts(doc, 0.995 * min(bw / max(w, 0.01), bh / max(h, 0.01)), exact=True)
            item.width = round(bw, 2)
            item.geometry_changed()
            x, y = self.place(o, bw, bh)
            y += (bh - item.size_mm()[1]) / 2
        else:
            w = item.size_mm()[0]
            # shortcut: Arial w miejsce czcionki drukarki (TSC Sans Serif) jest ~12% szerszy — poszerzamy zawijanie,
            # żeby wiersze łamały się jak w BarTenderze; dokładnie byłoby z metrykami czcionki drukarki
            wrap_k = 1.12 if replaced else 1.0
            if wrap and wrap_w > 0:  # pole ma szerokość z BarTendera; zawijamy tylko gdy wiersz naprawdę się nie mieści
                box = wrap_w * MIL * wrap_k
                item.width = round(box if w > box * 1.08 else max(box, w + 0.2), 2)
            else:
                item.width = round(w + 0.2, 2)  # stała szerokość: wyrównanie wierszy działa
            item.geometry_changed()
            x, y = self.place(o, *item.size_mm())
        item.setPos(items.mm(x), items.mm(y))
        return item.to_dict()

    # ------------------------------------------------------------ kod kreskowy
    def barcode(self, o):
        d = self.d
        sym = BARCODES.get(o["cls"])
        vals = _values(d, o["end"], o["stop"])
        if not sym or not vals:
            self.warn(f"„{o['name']}”: kod {o['cls'][2:-4] or o['cls']} nieobsługiwany — pominięto.")
            return None
        data = vals[0][0]
        if sym == "EAN-13" and len(data) == 13:
            data = data[:12]  # cyfrę kontrolną liczy program
        elif sym == "EAN-8" and len(data) == 8:
            data = data[:7]
        item = items.BarcodeItem()
        item.symbology, item.data = sym, data
        # za drugą kopią danych: szerokość symbolu i wysokość kresek [mils]
        m = re.compile(rb"\xff{8}([\s\S]{4})\x00\x00([\s\S]{4})\x00[\x00\x01]").search(d, vals[0][1], o["stop"])
        fonts = _fonts(d, vals[0][1], o["stop"])
        if fonts:
            fam, pt, bold, *_ = fonts[0][1]
            item.font_size, item.text_bold = round(pt, 1), bold
        item.geometry_changed()
        if item._error:
            self.warn(f"„{o['name']}”: nieprawidłowe dane kodu ({item._error}).")
        if m and item._pattern:
            item.module = round(_i32(m.group(1), 0) * MIL / len(item._pattern), 3)
            item.bar_height = round(_i32(m.group(2), 0) * MIL, 2)
        else:
            self.warn(f"„{o['name']}”: nie odczytano rozmiaru kodu — przyjęto domyślny.")
        item.geometry_changed()
        lead = items.to_mm(item._lead())
        w, h = item.size_mm()
        x, y = self.place(o, w - lead, h)  # BarTender liczy położenie od pierwszej kreski
        item.setPos(items.mm(x - lead), items.mm(y))
        return item.to_dict()

    # ------------------------------------------------------------ obraz
    def picture(self, o):
        d = self.d
        m = re.compile(rb"\xff\xfe\xff\x03((?:[a-zA-Z]\x00){3})").search(d, o["end"], o["stop"])
        data = None
        if m:
            e = m.end()
            w, h = _i32(d, e + 32) * MIL, _i32(d, e + 36) * MIL
            ext = m.group(1).decode("utf-16-le").lower()
            for k in re.finditer(rb"\xff\xfe\xff\x03" + re.escape(m.group(1)) + rb"([\s\S]{4})", d[e:o["stop"]]):
                n = _i32(k.group(1), 0)
                blob = d[e + k.end():e + k.end() + n]
                if 0 < n == len(blob):
                    data = blob
        if not data or w <= 0 or h <= 0:
            self.warn(f"„{o['name']}”: nie odczytano obrazu — pominięto.")
            return None
        img = self.render(data, ext)
        if img.isNull():
            self.warn(f"„{o['name']}”: format obrazu {ext} nieobsługiwany — pominięto.")
            return None
        x, y = self.place(o, w, h)
        qr = self.as_qr(img, w)
        if qr:
            qr.setPos(items.mm(x), items.mm(y))
            return qr.to_dict()
        item = items.ImageItem(img)
        item.w, item.h = round(w, 2), round(h, 2)
        item.setPos(items.mm(x), items.mm(y))
        return item.to_dict()

    @staticmethod
    def render(data, ext):
        if ext != "svg":
            return QImage.fromData(QByteArray(data))
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(data))
        if not r.isValid():
            return QImage()
        s = r.defaultSize().scaled(1600, 1600, Qt.KeepAspectRatio)
        img = QImage(s, QImage.Format_RGB32)
        img.fill(Qt.white)
        p = QPainter(img)
        r.render(p)
        p.end()
        # BarTender rysuje SVG bez pustych marginesów: kadr do treści
        ink = [(x, y) for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
               if QColor(img.pixel(x, y)).lightness() < 128]
        if ink:
            xs, ys = [p[0] for p in ink], [p[1] for p in ink]
            img = img.copy(min(xs), min(ys), max(xs) - min(xs) + 2, max(ys) - min(ys) + 2)
        return img

    @staticmethod
    def as_qr(img, w_mm):
        """Obraz z kodem QR -> edytowalny kod QR tej samej wielkości (albo None)."""
        try:
            import zxingcpp
            res = [r for r in zxingcpp.read_barcodes(img) if r.format.name == "QRCode"]
        except Exception:
            return None
        if len(res) != 1 or not res[0].text:
            return None
        item = items.Code2DItem()
        item.data, item.ecc = res[0].text, res[0].ec_level if res[0].ec_level in ("L", "M", "Q", "H") else "M"
        item.geometry_changed()
        if item._error:
            return None
        item.module = round(w_mm / len(item._m), 3)
        item.geometry_changed()
        return item

    # ------------------------------------------------------------ całość
    def run(self):
        out = []
        for o in _objects(self.d):
            c = o["cls"]
            if c in IGNORED:
                continue
            if c == "TextData":
                it = self.text(o)
            elif c.startswith("Bc"):
                it = self.barcode(o)
            elif c == "PictureData":
                it = self.picture(o)
            else:
                self.warn(f"„{o['name']}” ({c}): typ obiektu nieobsługiwany — pominięto.")
                it = None
            if it:
                # odnośnik do obiektu wzoru: przy zapisie .btw tu trafią zmiany (dx/dy: róg elementu - zaczepienie)
                it["btw"] = {"pos": o["pos"], "name": o["name"],
                             "dx": round(it["x"] - o["x"] * MIL, 3), "dy": round(it["y"] - o["y"] * MIL, 3)}
                if it["kind"] == "code2d":
                    it["btw"]["qr"] = it["data"]
                out.append(it)
        for face in sorted(self._replaced):
            self.warn(f"Czcionka „{face}” nie jest zainstalowana — zastąpiona Arial.")
        doc = {"version": 1, "label": {"w": round(self.w, 2), "h": round(self.h, 2), "radius": 0, "name": ""},
               "print": copy.deepcopy(items.DEFAULT_PRINT), "items": out,
               "btw_template": base64.b64encode(self.raw).decode()}
        return doc, self.warnings


def read_btw(path):
    """Plik .btw -> (dokument .etk, lista ostrzeżeń). Wymaga działającej QApplication."""
    with open(path, "rb") as fh:
        doc, warnings = Importer(fh.read()).run()
    doc["label"]["name"] = os.path.splitext(os.path.basename(path))[0]
    return doc, warnings


# ---------------------------------------------------------------- zapis na podstawie wzoru

def _design(cls):
    return cls in ("TextData", "PictureData") or cls.startswith("Bc")


def _spread(parts, new):
    """Nowy tekst rozłożony na wartości wzoru (każda ma swoją czcionkę): zmieniony odcinek trafia do wartości,
    w której się zaczyna. -> (nowe wartości, czy połączono kilka wartości)."""
    old = "".join(parts)
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new)) - p and old[-1 - s] == new[-1 - s]:
        s += 1
    ends = list(itertools.accumulate(len(x) for x in parts))
    starts = [e - len(x) for e, x in zip(ends, parts)]
    i = next(k for k in range(len(parts)) if p <= ends[k] or k == len(parts) - 1)
    if p == ends[i] and parts[i].endswith("\n") and i + 1 < len(parts):
        i += 1  # pisanie zaraz po podziale wiersza należy do następnego wiersza
    j = i
    while j + 1 < len(parts) and starts[j + 1] < len(old) - s:
        j += 1
    out = list(parts)
    out[i] = old[starts[i]:p] + new[p:len(new) - s] + old[len(old) - s:ends[j]]
    for k in range(i + 1, j + 1):
        out[k] = ""
    return out, j > i


def _svg_qr(data, ecc):
    """SVG kodu QR w tym samym układzie co w plikach BarTendera (2 jednostki/moduł, margines 4 moduły)."""
    m, _ = symbols.qr_matrix(data, ecc)
    size = (len(m) + 8) * 2
    path = "".join(f"M{8 + 2 * x},{8 + 2 * y}H{10 + 2 * x}V{10 + 2 * y}H{8 + 2 * x}z"
                   for y, row in enumerate(m) for x, on in enumerate(row) if on)
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            f'<svg width="{size}mm" height="{size}mm" version="1.1" viewBox="0 0 {size} {size}" '
            f'xmlns="http://www.w3.org/2000/svg"><path d="{path}" id="qr-path" fill="#000000" fill-opacity="1" '
            'fill-rule="nonzero" stroke="none"/></svg>').encode()


def _runs(it):
    """Fragmenty tekstu elementu: [(tekst z \\n, (rodzina, pt, pogrubienie, kursywa, podkreślenie))], sąsiednie
    o tym samym formacie połączone (BarTender trzyma każdy fragment jako osobne źródło danych)."""
    item = items.make_item(it)  # element musi żyć, dopóki czytamy jego dokument
    doc = item.document()
    out = []
    block = doc.begin()
    while block.isValid():
        frags = block.begin()
        while not frags.atEnd():
            f = frags.fragment()
            if f.isValid():
                cf = f.charFormat()
                fam = (cf.fontFamilies() or [doc.defaultFont().family()])[0]
                pt = cf.fontPointSize() or doc.defaultFont().pointSizeF()
                key = (fam, round(pt, 2), cf.fontWeight() >= 600, cf.fontItalic(), cf.fontUnderline())
                text = f.text().replace(" ", "\n")
                if out and out[-1][1] == key:
                    out[-1] = (out[-1][0] + text, key)
                else:
                    out.append((text, key))
            frags += 1
        block = block.next()
        if block.isValid() and out:
            out[-1] = (out[-1][0] + "\n", out[-1][1])
    return out or [("", ("Arial", 10.0, False, False, False))]


class Writer:
    def __init__(self, doc, template=None):
        """template: bajty pliku .btw jako szablon dla etykiety spoza BarTendera (bez doc["btw_template"])."""
        self.doc = doc
        self.auto = template is not None
        self.raw = template if self.auto else base64.b64decode(doc["btw_template"])
        self.start, self.d = _stream(self.raw)
        self.edits, self.notes = [], []  # edycje: (od, do, nowe bajty) w strumieniu dokumentu

    def note(self, s):
        if s not in self.notes:
            self.notes.append(s)

    # ---------------------------------------------------------- szablon: przypisanie elementów do obiektów
    def auto_map(self, objs):
        """Elementy etykiety -> obiekty szablonu tego samego rodzaju. Tekst idzie do pola z co najmniej tyloma
        fragmentami (źródłami danych), ile ma formatów — najlepiej z identycznym układem pogrubień."""
        d = self.d
        free = sorted(objs.values(), key=lambda o: (o["y"], o["x"]))
        pairs = []
        order = sorted(self.doc["items"], key=lambda it: -len(_runs(it)) if it["kind"] == "text" else 0)
        for it in order:
            if it["kind"] == "text":
                runs = _runs(it)
                cands = []
                for o in free:
                    if o["cls"] != "TextData":
                        continue
                    vals = _values(d, o["end"], o["stop"])
                    if len(vals) >= len(runs):
                        # fragmenty bez własnej czcionki dzielą wspólną czcionkę pola: muszą mieć ten sam format
                        shared = {r[1] for v, r in zip(vals, runs) if v[2] is None and r[0].strip()}
                        cands.append((len(shared) > 1, len(vals) - len(runs), o["y"], o["x"], o))
                o = min(cands, key=lambda c: c[:4])[4] if cands else None
            else:
                want = {"barcode": lambda c: c.startswith("Bc"), "code2d": lambda c: c == "PictureData"}.get(it["kind"])
                o = next((o for o in free if want and want(o["cls"])), None)
            if o is None:
                pairs.append((it, None))
                continue
            free.remove(o)
            w, h = items.make_item(it).size_mm()
            col, row = o["anchor"] % 3, min(2, o["anchor"] // 3)
            lead = items.to_mm(items.make_item(it)._lead()) if it["kind"] == "barcode" else 0
            ref = {"pos": o["pos"], "name": o["name"], "full": True,
                   "dx": -(lead + col * (w - lead) / 2), "dy": -row * h / 2}
            pairs.append((it, ref))
        for o in free:  # niewykorzystane pola szablonu: puste, żeby nie drukowały wzorcowej treści
            if o["cls"] == "TextData":
                for v in _values(d, o["end"], o["stop"]):
                    self.edits.append((v[3], v[1], _cs("")))
                self.note(f"Pole szablonu „{o['name']}” niewykorzystane — wyczyszczone.")
            else:
                self.note(f"Obiekt szablonu „{o['name']}” niewykorzystany — zostaje w pliku.")
        return pairs

    def font(self, s, fmt):
        """Podmiana LOGFONT od s (i wielkości jako float zaraz za nim, w archiwum 2022)."""
        fam, pt, bold, italic, under = fmt
        self.edits += [(s, s + 4, struct.pack("<i", -round(pt * 20))),
                       (s + 16, s + 22, struct.pack("<i", 700 if bold else 400) + bytes([italic, under])),
                       (s + 28, s + 92, fam.encode("utf-16-le")[:62].ljust(64, b"\0"))]
        if struct.unpack_from("<f", self.d, s + 92)[0] > 0:
            self.edits.append((s + 92, s + 96, struct.pack("<f", pt)))

    def text_full(self, o, it, label):
        """Tekst z formatowaniem: fragmenty -> źródła danych, ich czcionki, zawijanie i wyrównanie."""
        d = self.d
        vals = _values(d, o["end"], o["stop"])
        runs = _runs(it)
        runs += [("", runs[-1][1])] * (len(vals) - len(runs))
        fonts = _fonts(d, o["end"], o["stop"])
        default = {}  # format dla wartości bez własnej czcionki (wspólna czcionka obiektu)
        for v, (text, fmt) in zip(vals, runs):
            self.edits.append((v[3], v[1], _cs(text.replace("\n", "\r"))))
            if v[2]:
                self.font(v[1] + 13, fmt)
            elif text:
                default.setdefault(fmt, text)
        if len(default) > 1:
            self.note(f"{label}: w szablonie za mało fragmentów z własną czcionką — część tekstu dostała "
                      "wspólną czcionkę pola.")
        if default and fonts:
            fmt = next(iter(default))
            own = {v[1] + 13 for v in vals if v[2]}
            for s, _f in fonts:  # wspólna czcionka (i jej kopia dla czcionek drukarki)
                if s not in own:
                    self.font(s, fmt)
        p = _PARA.search(d, vals[-1][1], o["stop"])
        if p:
            align = {"do środka": 1, "do prawej": 2, "wyjustuj": 3}.get(it.get("align"), 0)
            w = it.get("width") or 0
            self.edits += [(p.start() + 8, p.start() + 16, struct.pack("<ii", 1 if w > 0 else 0, align)),
                           (p.start() + 20, p.start() + 24, struct.pack("<i", round(w / MIL) if w > 0 else 2000))]
        if it.get("line_height", 100) != 100:
            self.note(f"{label}: interlinii ({it['line_height']}%) BarTender nie dostaje — zostaje ze szablonu.")

    def text(self, o, it, label):
        d = self.d
        vals = _values(d, o["end"], o["stop"])
        parts = _shown(vals, _fixed_box(d, o, vals)[0]) if vals else []
        new = items.make_item(it).content().replace(" ", "\n")
        if not vals or new == "".join(parts):
            return
        if re.search(r"\{[^}]+\}", new):
            self.note(f"{label}: zmienne {{…}} BarTender pokaże jako zwykły tekst.")
        out, merged = _spread(parts, new)
        if merged:
            self.note(f"{label}: zmiana objęła fragmenty o różnym formatowaniu — dostały format pierwszego.")
        for v, was, now in zip(vals, parts, out):
            if now != was:
                tail = v[0][len(was):]  # końcowe \r, które BarTender pomija w polu
                self.edits.append((v[3], v[1], _cs(now.replace("\n", "\r") + tail)))

    def barcode(self, o, it, label, full=False):
        d = self.d
        vals = _values(d, o["end"], o["stop"])
        if not vals:
            return
        if full:  # etykieta spoza BarTendera: szerokość symbolu, wysokość kresek i czcionka cyfr jak w programie
            m = re.compile(rb"\xff{8}([\s\S]{4})\x00\x00([\s\S]{4})\x00[\x00\x01]").search(d, vals[0][1], o["stop"])
            b = items.make_item(it)
            if m and b._pattern:
                self.edits += [(m.start() + 8, m.start() + 12, struct.pack("<i", round(b.module * len(b._pattern) / MIL))),
                               (m.start() + 14, m.start() + 18, struct.pack("<i", round(b.bar_height / MIL)))]
            fonts = _fonts(d, vals[0][1], o["stop"])
            if fonts:
                self.font(fonts[0][0], ("Arial", b.font_size, b.text_bold, False, False))
        if it["symbology"] != BARCODES.get(o["cls"]):
            self.note(f"{label}: zmiany rodzaju kodu BarTender nie dostanie — zostaje {BARCODES.get(o['cls'], o['cls'])}.")
            return
        old, new = vals[0][0], it["data"]
        if it["symbology"] in ("EAN-13", "EAN-8", "UPC-A"):
            try:  # pełny numer z cyfrą kontrolną, jak w pliku BarTendera
                new = re.sub(r"\D", "", symbols.barcode_modules(it["symbology"], new)[1])
            except Exception as ex:
                self.note(f"{label}: nieprawidłowe dane kodu ({ex}) — nie zapisano.")
                return
        if new == old:
            return
        for m in re.finditer(re.escape(_cs(old)), d[o["end"]:o["stop"]]):  # dane i ich druga kopia
            self.edits.append((o["end"] + m.start(), o["end"] + m.end(), _cs(new)))

    def qr(self, o, it, ref, label):
        d = self.d
        svg_tag = re.escape(_cs("svg"))
        blob = None
        for m in re.finditer(svg_tag + rb"([\s\S]{4})<", d[o["end"]:o["stop"]]):
            a = o["end"] + m.end() - 1
            n = _i32(m.group(1), 0)
            if _i32(d, a + n + 10) & 0xFFFFFFFF == zlib.crc32(d[a:a + n]):  # za obrazem: CRC32 obrazu
                blob = a, n
        props = re.compile(svg_tag).search(d, o["end"], o["stop"])
        if not blob or not props:
            self.note(f"{label}: nie znaleziono obrazu kodu QR we wzorze — nie zapisano.")
            return
        a, n = blob
        if it["data"] != ref.get("qr"):
            try:
                svg = _svg_qr(it["data"], it["ecc"])
            except Exception as ex:
                self.note(f"{label}: nieprawidłowe dane kodu QR ({ex}) — nie zapisano.")
                return
            self.edits += [(a - 4, a + n, struct.pack("<I", len(svg)) + svg),
                           (a + n + 10, a + n + 14, struct.pack("<I", zlib.crc32(svg)))]
        w = items.make_item(it).size_mm()[0]
        e = props.end()  # rozmiar obrazu [mils] w ustawieniach obiektu
        if abs(w - _i32(d, e + 32) * MIL) > 0.05:
            self.edits.append((e + 32, e + 40, struct.pack("<ii", round(w / MIL), round(w / MIL))))

    def preview(self, header):
        """Nowy podgląd (miniatura w BarTenderze i w Windows): pierwszy PNG z długością przed nim."""
        i = header.find(b"\x89PNG")
        n = _i32(header, i - 4) if i >= 4 else 0
        if n <= 0 or header[i + n - 8:i + n - 4] != b"IEND":
            return header
        import output
        from PySide6.QtCore import QBuffer
        old = QImage.fromData(QByteArray(header[i:i + n]))
        side = old.width() or 734
        lw, lh = self.doc["label"]["w"], self.doc["label"]["h"]
        lab = output.render_image(self.doc, dpi=max(30, int((side - 4) / max(lw, lh) * 25.4)))
        img = QImage(side, side, QImage.Format_RGB32)
        img.fill(QColor(old.pixel(2, 2)) if not old.isNull() else QColor(112, 112, 112))
        p = QPainter(img)
        x0, y0 = (side - lab.width()) // 2, (side - lab.height()) // 2
        p.drawImage(x0, y0, lab)
        p.setPen(Qt.black)
        p.drawRect(x0 - 1, y0 - 1, lab.width() + 1, lab.height() + 1)
        p.end()
        buf = QBuffer()
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        png = bytes(buf.data())
        return header[:i - 4] + struct.pack("<I", len(png)) + png + header[i + n:]

    def run(self):
        objs = {o["pos"]: o for o in _objects(self.d) if _design(o["cls"])}
        if self.auto:
            m = re.search(rb"<TemplateSize>\s*([\d.,]+)\s*x\s*([\d.,]+)\s*mm", self.raw)
            size = tuple(float(v.replace(b",", b".")) for v in m.groups()) if m else None
            lab = (self.doc["label"]["w"], self.doc["label"]["h"])
            if size and max(abs(a - b) for a, b in zip(size, lab)) > 0.1:
                self.note(f"Szablon ma rozmiar {size[0]:g} × {size[1]:g} mm, etykieta {lab[0]:g} × {lab[1]:g} mm — "
                          "w pliku zostaje rozmiar szablonu.")
            pairs = self.auto_map(objs)
        else:
            pairs = [(it, it.get("btw") or {}) for it in self.doc["items"]]
        used = set()
        for it, ref in pairs:
            ref = ref or {}
            o = objs.get(ref.get("pos"))
            content = items.make_item(it).content().replace("\n", " ")
            label = f"„{content[:30]}”" if content else it["kind"]
            if not o or o["name"] != ref.get("name") or o["pos"] in used:
                self.note(f"{label}: " + ("brak pasującego pola w szablonie — nie trafi do BarTendera." if self.auto
                                          else "dodany w programie — w pliku BarTendera go nie będzie."))
                continue
            used.add(o["pos"])
            x, y = it["x"] - ref["dx"], it["y"] - ref["dy"]
            if abs(x - o["x"] * MIL) > 0.01 or abs(y - o["y"] * MIL) > 0.01:
                self.edits.append((o["pos"], o["pos"] + 8, struct.pack("<ii", round(x / MIL), round(y / MIL))))
            if it.get("rotation"):
                self.note(f"{label}: obrót nie jest zapisywany do BarTendera.")
            if it["kind"] == "text" and o["cls"] == "TextData":
                (self.text_full if ref.get("full") else self.text)(o, it, label)
            elif it["kind"] == "barcode" and o["cls"].startswith("Bc"):
                self.barcode(o, it, label, full=ref.get("full", False))
            elif it["kind"] == "code2d" and o["cls"] == "PictureData":
                self.qr(o, it, ref, label)
        for o in objs.values():
            if o["pos"] not in used and not self.auto:  # w szablonie wolne pola opisuje auto_map
                self.note(f"„{o['name']}”: usunięty w programie — w pliku BarTendera zostaje.")
        d = self.d
        for a, b, new in sorted(self.edits, key=lambda e: e[0], reverse=True):
            d = d[:a] + new + d[b:]
        level = {0x01: 1, 0x5e: 3, 0x9c: 6, 0xda: 9}[self.raw[self.start + 1]]
        return self.preview(self.raw[:self.start]) + zlib.compress(d, level)


def write_btw(doc, path, template=None):
    """Zapis .btw -> lista uwag. Wzór: doc["btw_template"] (etykieta z BarTendera: treści, kody, położenie)
    albo template = bajty szablonu .btw (etykieta z programu: także czcionki, zawijanie, wyrównanie)."""
    if template is None and not doc.get("btw_template"):
        raise ValueError("Ta etykieta nie pochodzi z pliku BarTendera — wybierz szablon .btw.")
    w = Writer(doc, template)
    data = w.run()
    _stream(data)  # kontrola: plik da się odczytać
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)  # zapis atomowy
    return w.notes

"""Wyjście: render, ZPL, druk RAW / TCP / sterownik Windows, eksport plików i dokumentacja wymiarowa."""
import base64
import ctypes
import datetime
import html
import socket
import zlib
from ctypes import wintypes

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QPolygonF,
                           QTextDocument, QTransform)

from items import BarcodeItem, Code2DItem, LabelScene, TextItem, mm, to_mm

KIND_NAMES = {"text": "Tekst", "barcode": "Kod kreskowy", "code2d": "Kod 2D", "rect": "Prostokąt",
              "ellipse": "Elipsa", "line": "Linia", "image": "Grafika"}


def dots(v_mm, dpi):
    return round(v_mm / 25.4 * dpi)


def build_scene(doc, vars=None, dpi=None, hires=True):
    """Scena do druku. Przy znanym DPI moduły kodów i ich pozycje wyrównuje do pełnych punktów głowicy,
    bo kreska o ułamku punktu drukuje się nierówno i psuje czytelność."""
    s = LabelScene(preview=True)
    s.load_doc(doc, vars if vars is not None else {})
    if hires:
        for it in s.label_items():
            if isinstance(it, TextItem):
                it.hires()
    if dpi:
        for it in s.label_items():
            if isinstance(it, (BarcodeItem, Code2DItem)):
                it.module = max(1, round(it.module / 25.4 * dpi)) * 25.4 / dpi
                it.geometry_changed()
                px = 25.4 / dpi
                it.setPos(mm(round(to_mm(it.pos().x()) / px) * px), mm(round(to_mm(it.pos().y()) / px) * px))
    return s


def render_image(doc, vars=None, dpi=203, mono=False):
    s = build_scene(doc, vars, dpi)
    w, h = dots(s.label["w"], dpi), dots(s.label["h"], dpi)
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(Qt.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    s.render(p, QRectF(0, 0, w, h), s.label_rect())
    p.end()
    if mono:
        img = img.convertToFormat(QImage.Format_Mono, Qt.ThresholdDither | Qt.MonoOnly)
    return img


def roll_offset_dots(pr):
    """Przesunięcie z ustawień (układ projektu, jak na ekranie) w układzie głowicy: po obrocie i lustrze."""
    dpi, a = pr["dpi"], pr["orientation"] % 360
    ox, oy = dots(pr["offset_x"], dpi), dots(pr["offset_y"], dpi)
    # obrót wektora jak QTransform().rotate(a) obrazu (oś y w dół, kąt zgodnie z zegarem)
    dx, dy = {0: (ox, oy), 90: (-oy, ox), 180: (-ox, -oy), 270: (oy, -ox)}[a]
    return (-dx if pr["mirror"] else dx), dy


def roll_image(doc, vars, pr):
    """Obraz dokładnie taki, jaki trafi na głowicę: kolumny, obrót na rolce, lustro."""
    dpi = pr["dpi"]
    one = render_image(doc, vars, dpi)
    cols = max(1, int(pr["columns"]))
    gap = dots(pr["col_gap"], dpi)
    # przesunięcie w układzie projektu (jak na ekranie), przed obrotem — niezależnie od kierunku na rolce
    ox, oy = dots(pr["offset_x"], dpi), dots(pr["offset_y"], dpi)
    img = QImage(one.width() * cols + gap * (cols - 1), one.height(), QImage.Format_RGB32)
    img.fill(Qt.white)
    p = QPainter(img)
    for c in range(cols):
        p.drawImage(c * (one.width() + gap) + ox, oy, one)
    p.end()
    if pr["orientation"]:
        img = img.transformed(QTransform().rotate(pr["orientation"]))
    if pr["mirror"]:
        img = img.flipped(Qt.Horizontal)
    return img.convertToFormat(QImage.Format_Mono, Qt.ThresholdDither | Qt.MonoOnly)


# ---------------------------------------------------------------- ZPL

def _crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def mono_bytes(img):
    """Bity obrazu Mono w kolejności ZPL (1 = czarny), bez wyrównania wierszy."""
    bpr = (img.width() + 7) // 8
    black_is_one = QColor(img.color(1)).lightness() < 128
    raw = bytes(img.constBits())
    pad_mask = (0xFF << (bpr * 8 - img.width())) & 0xFF
    out = bytearray()
    for y in range(img.height()):
        row = bytearray(raw[y * img.bytesPerLine(): y * img.bytesPerLine() + bpr])
        if not black_is_one:
            row = bytearray(b ^ 0xFF for b in row)
        row[-1] &= pad_mask  # bity poza szerokością muszą być białe
        out += row
    return bytes(out), bpr


def zpl_graphic(img):
    data, bpr = mono_bytes(img)
    b64 = base64.b64encode(zlib.compress(data, 9))
    return f"^GFA,{len(data)},{len(data)},{bpr},:Z64:{b64.decode()}:{_crc16(b64):04X}"


def zpl_label(img, pr, qty):
    return "\n".join([
        "^XA",
        f"~TA{int(pr['tear_off']):03d}",
        f"^MM{pr['mode']}",
        f"^MN{pr['media']}",
        f"~SD{int(pr['darkness']):02d}",
        f"^PR{int(pr['speed'])}",
        f"^PW{img.width()}",
        f"^LL{img.height()}",
        "^LH0,0",
        "^LS0",  # przesunięcie jest już w obrazie (roll_image); zerujemy wartości zapamiętane w drukarce
        "^LT0",
        "^PON",
        "^FO0,0" + zpl_graphic(img) + "^FS",
        f"^PQ{int(qty)},0,1,Y",
        "^XZ",
    ])


def build_zpl(doc, records, copies):
    pr = doc["print"]
    return "\n".join(zpl_label(roll_image(doc, v, pr), pr, copies) for v in records)


class _DOCINFO(ctypes.Structure):
    _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]


def send_raw_to_queue(printer, data, job="Etykieta"):
    """Wysyła surowe dane do kolejki Windows z typem RAW (sterownik ich nie przetwarza)."""
    ws = ctypes.WinDLL("winspool.drv")
    h = wintypes.HANDLE()
    if not ws.OpenPrinterW(printer, ctypes.byref(h), None):
        raise OSError(f"Nie można otworzyć drukarki „{printer}”")
    try:
        info = _DOCINFO(job, None, "RAW")
        if not ws.StartDocPrinterW(h, 1, ctypes.byref(info)):
            raise OSError("StartDocPrinter nie powiodło się")
        try:
            ws.StartPagePrinter(h)
            written = wintypes.DWORD()
            buf = data if isinstance(data, bytes) else data.encode("ascii")
            if not ws.WritePrinter(h, buf, len(buf), ctypes.byref(written)) or written.value != len(buf):
                raise OSError("Wysłano niepełne dane do drukarki")
            ws.EndPagePrinter(h)
        finally:
            ws.EndDocPrinter(h)
    finally:
        ws.ClosePrinter(h)


def send_tcp(host, port, data):
    with socket.create_connection((host, int(port)), timeout=10) as s:
        s.sendall(data if isinstance(data, bytes) else data.encode("ascii"))


# ---------------------------------------------------------------- TSC / TSPL

# tryby wyjścia ZPL -> polecenia TSPL
# SET TEAR/PEEL/CUTTER/REWIND drukarka zapamiętuje po wyłączeniu, więc każdy tryb ustawia wszystkie
TSPL_MODE = {"T": ["SET TEAR ON", "SET PEEL OFF", "SET CUTTER OFF", "SET REWIND OFF"],
             "P": ["SET TEAR OFF", "SET PEEL ON", "SET CUTTER OFF", "SET REWIND OFF"],
             "C": ["SET PEEL OFF", "SET CUTTER 1", "SET REWIND OFF"],
             "D": ["SET PEEL OFF", "SET CUTTER BATCH", "SET REWIND OFF"],
             "R": ["SET TEAR OFF", "SET PEEL OFF", "SET CUTTER OFF", "SET REWIND ON"],  # wewnętrzny nawijak
             "A": ["SET TEAR OFF", "SET PEEL OFF", "SET CUTTER OFF", "SET REWIND OFF"]}


def tspl_image(doc, vars, pr, size_mm):
    """Obraz dla TSC i przesunięcie w poprzek głowicy (punkty) do polecenia SHIFT.
    W poprzek przesunięcie w obrazie zawsze coś ucina: etykieta wystaje poza kolumnę 0 obrazu, a ani
    dosztukowanie obrazu, ani szersze SIZE nie przesuwają druku (ustalone wydrukami na MH341 22.10.2026).
    Dlatego w poprzek SHIFT x (±1 cal), a wzdłuż wysuwu zwykłe przesunięcie w obrazie i przycięcie do długości."""
    dpi = pr["dpi"]
    dx, dy = roll_offset_dots(pr)
    base = roll_image(doc, vars, dict(pr, offset_x=0, offset_y=0)).convertToFormat(QImage.Format_RGB32)
    img = QImage(base.width(), dots(size_mm[1], dpi), QImage.Format_RGB32)
    img.fill(Qt.white)
    p = QPainter(img)
    p.drawImage(0, dy, base)
    p.end()
    shift_x = max(-dpi, min(dpi, pr.get("tspl_shift_sign", 1) * dx))  # zakres SHIFT: ±1 cal
    return img.convertToFormat(QImage.Format_Mono, Qt.ThresholdDither | Qt.MonoOnly), size_mm, shift_x


def tspl_label(img, size_mm, shift_x, pr, qty):
    dpi = pr["dpi"]
    data, bpr = mono_bytes(img)
    data = bytes(b ^ 0xFF for b in data)  # w TSPL bit 0 = punkt czarny
    # GAP trzeba wysłać zawsze: przełącza drukarkę na czujnik przerwy (bez niego etykieta wchodzi na dwie)
    gap = pr.get("gap") or 3.0
    media = {"Y": f"GAP {gap:.1f} mm,0 mm", "M": f"BLINE {gap:.1f} mm,0 mm", "N": "GAP 0 mm,0 mm"}[pr["media"]]
    head = [f"SIZE {size_mm[0]:.2f} mm,{size_mm[1]:.2f} mm", media,
            f"DIRECTION {pr.get('tspl_direction', 1)},0", "REFERENCE 0,0", f"SHIFT {shift_x},0",
            f"OFFSET {pr['tear_off'] * 25.4 / dpi:.2f} mm",
            f"SPEED {int(pr['speed'])}", f"DENSITY {min(15, round(pr['darkness'] / 2))}",
            *TSPL_MODE[pr["mode"]], "CLS", f"BITMAP 0,0,{bpr},{img.height()},0,"]
    return "\r\n".join(head).encode("ascii") + data + f"\r\nPRINT 1,{int(qty)}\r\n".encode("ascii")


def build_tspl(doc, records, copies):
    pr = doc["print"]
    size = windows_page_size(pr, doc["label"])  # wymiar w mm po obrocie i z kolumnami
    return b"".join(tspl_label(*tspl_image(doc, v, pr, size), pr, copies) for v in records)


def build_job(doc, records, copies):
    """Zadanie w języku wybranej drukarki."""
    return (build_tspl if doc["print"]["method"] == "tspl" else build_zpl)(doc, records, copies)


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class _IFDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", _GUID), ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.c_void_p)]


# GUID_DEVINTERFACE_USBPRINT {28d78fad-5a12-11d1-ae5b-0000f803a8c2}
_USBPRINT = _GUID(0x28d78fad, 0x5a12, 0x11d1, (ctypes.c_ubyte * 8)(0xae, 0x5b, 0x00, 0x00, 0xf8, 0x03, 0xa8, 0xc2))


def usb_printers():
    """Ścieżki urządzeń drukarek USB (sterownik usbprint Windows), także bez zainstalowanej kolejki."""
    sa = ctypes.WinDLL("setupapi")
    sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    sa.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(_GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    sa.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_GUID),
                                               wintypes.DWORD, ctypes.POINTER(_IFDATA)]
    sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IFDATA), ctypes.c_void_p,
                                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    h = sa.SetupDiGetClassDevsW(ctypes.byref(_USBPRINT), None, None, 0x02 | 0x10)  # PRESENT | DEVICEINTERFACE
    paths = []
    try:
        i = 0
        while True:
            d = _IFDATA()
            d.cbSize = ctypes.sizeof(_IFDATA)
            if not sa.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(_USBPRINT), i, ctypes.byref(d)):
                break
            size = wintypes.DWORD()
            sa.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), None, 0, ctypes.byref(size), None)
            buf = ctypes.create_string_buffer(size.value)
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if sa.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), buf, size, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
            i += 1
    finally:
        sa.SetupDiDestroyDeviceInfoList(h)
    return paths


def send_usb(data, prefer="vid_1203"):
    """Pisze bezpośrednio do drukarki USB (domyślnie pierwsza TSC — VID 1203)."""
    paths = usb_printers()
    path = next((p for p in paths if prefer in p.lower()), paths[0] if len(paths) == 1 else None)
    if not path:
        raise OSError("Nie znaleziono drukarki TSC na USB. Sprawdź kabel i czy drukarka jest włączona."
                      if not paths else f"Podłączono kilka drukarek USB, żadna nie pasuje do „{prefer}”.")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    k.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                            ctypes.c_void_p]
    h = k.CreateFileW(path, 0x40000000, 0x3, None, 3, 0, None)  # GENERIC_WRITE, share r/w, OPEN_EXISTING
    if h in (None, wintypes.HANDLE(-1).value):
        raise OSError(f"Drukarka USB jest zajęta lub niedostępna (błąd {ctypes.get_last_error()}).")
    try:
        data = data if isinstance(data, bytes) else data.encode("ascii")
        pos = 0
        while pos < len(data):
            chunk = data[pos:pos + 65536]
            n = wintypes.DWORD()
            if not k.WriteFile(h, chunk, len(chunk), ctypes.byref(n), None) or n.value == 0:
                raise OSError(f"Przerwano wysyłanie do drukarki USB (błąd {ctypes.get_last_error()}).")
            pos += n.value
    finally:
        k.CloseHandle(h)


# ---------------------------------------------------------------- sterownik Windows (Datamax itp.)

def windows_page_size(pr, label):
    cols = max(1, int(pr["columns"]))
    w = label["w"] * cols + pr["col_gap"] * (cols - 1)
    h = label["h"]
    return (h, w) if pr["orientation"] in (90, 270) else (w, h)


def setup_printer(printer, doc):
    pr, label = doc["print"], doc["label"]
    w, h = windows_page_size(pr, label)
    printer.setFullPage(True)
    printer.setPageLayout(QPageLayout(QPageSize(QSizeF(w, h), QPageSize.Millimeter, "Etykieta"),
                                      QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))


def paint_windows(printer, doc, records, copies):
    """Rysuje wektorowo na stronie drukarki; obrót/lustro/przesunięcie jak dla ZPL."""
    pr, label = doc["print"], doc["label"]
    dpi = printer.resolution()
    pw, ph = windows_page_size(pr, label)
    cols = max(1, int(pr["columns"]))
    k = dpi / 25.4  # punktów drukarki na mm
    p = QPainter(printer)
    first = True
    for v in records:
        s = build_scene(doc, v, dpi)
        for _ in range(int(copies)):
            if not first:
                printer.newPage()
            first = False
            p.save()
            p.translate(pw * k / 2, ph * k / 2)
            if pr["mirror"]:
                p.scale(-1, 1)
            p.rotate(pr["orientation"])
            rw = label["w"] * cols + pr["col_gap"] * (cols - 1)
            p.translate(-rw * k / 2, -label["h"] * k / 2)
            p.translate(pr["offset_x"] * k, pr["offset_y"] * k)  # w układzie projektu, jak w roll_image
            for c in range(cols):
                x = c * (label["w"] + pr["col_gap"]) * k
                s.render(p, QRectF(x, 0, label["w"] * k, label["h"] * k), s.label_rect())
            p.restore()
    p.end()


# ---------------------------------------------------------------- eksport plików

def export_png(doc, path, dpi, vars):
    if not render_image(doc, vars, dpi).save(path, "PNG"):
        raise OSError("Nie udało się zapisać " + path)


def _pdf_writer(path, w_mm, h_mm, landscape=False):
    wr = QPdfWriter(path)
    wr.setResolution(600)
    wr.setPageLayout(QPageLayout(QPageSize(QSizeF(w_mm, h_mm), QPageSize.Millimeter),
                                 QPageLayout.Landscape if landscape else QPageLayout.Portrait,
                                 QMarginsF(0, 0, 0, 0)))
    return wr


def export_pdf(doc, path, vars):
    s = build_scene(doc, vars)
    wr = _pdf_writer(path, s.label["w"], s.label["h"])
    p = QPainter(wr)
    s.render(p, QRectF(0, 0, wr.width(), wr.height()), s.label_rect())
    p.end()


def export_svg(doc, path, vars):
    from PySide6.QtSvg import QSvgGenerator
    s = build_scene(doc, vars)
    g = QSvgGenerator()
    g.setFileName(path)
    g.setResolution(96)
    r = s.label_rect()
    g.setSize(r.size().toSize())
    g.setViewBox(r)
    p = QPainter(g)
    s.render(p, r, r)
    p.end()


# ---------------------------------------------------------------- dokumentacja wymiarowa

SCALES = [10, 8, 5, 4, 3, 2.5, 2, 1.5, 1, 0.75, 0.5, 0.25]


def _arrow(p, tip, direction, size):
    d = QPointF(direction.x() * size, direction.y() * size)
    n = QPointF(-direction.y() * size * 0.35, direction.x() * size * 0.35)
    p.drawPolygon(QPolygonF([tip, tip - d + n, tip - d - n]))


def _dim(p, a, b, offset, text, k, vertical=False):
    """Linia wymiarowa między punktami a i b (w px strony), odsunięta o offset."""
    pen = p.pen()
    p.setPen(QPen(QColor(200, 0, 0), k * 0.15))
    p.setBrush(QColor(200, 0, 0))
    if vertical:
        a2, b2 = QPointF(a.x() + offset, a.y()), QPointF(b.x() + offset, b.y())
        ext = QPointF(k * 1.5 * (1 if offset > 0 else -1), 0)
        dirv = QPointF(0, 1)
    else:
        a2, b2 = QPointF(a.x(), a.y() + offset), QPointF(b.x(), b.y() + offset)
        ext = QPointF(0, k * 1.5 * (1 if offset > 0 else -1))
        dirv = QPointF(1, 0)
    p.drawLine(a, a2 + ext)
    p.drawLine(b, b2 + ext)
    p.drawLine(a2, b2)
    _arrow(p, a2, QPointF(-dirv.x(), -dirv.y()), k * 2)
    _arrow(p, b2, dirv, k * 2)
    p.save()
    mid = (a2 + b2) / 2
    p.translate(mid)
    if vertical:
        p.rotate(-90)
    p.setPen(QColor(200, 0, 0))
    p.drawText(QRectF(-k * 30, -k * 5, k * 60, k * 4.5), Qt.AlignHCenter | Qt.AlignBottom, text)
    p.restore()
    p.setPen(pen)


def fmt(v):
    return f"{v:.2f}".replace(".", ",")


def item_rows(scene):
    dpi = scene.print["dpi"]
    rows = []
    # numeracja w kolejności czytania: od góry, potem od lewej
    ordered = sorted(scene.label_items(), key=lambda i: (round(i.sceneBoundingRect().top() / mm(2)),
                                                         i.sceneBoundingRect().left()))
    for n, it in enumerate(ordered, 1):
        w, h = it.size_mm()
        det = it.doc_details()
        if isinstance(it, (BarcodeItem, Code2DItem)):
            d = max(1, round(it.module / 25.4 * dpi))
            eff = d * 25.4 / dpi
            det += f"\nNa {dpi} dpi: moduł {d} pkt = {eff:.3f} mm"
        content = it.content()
        rows.append((n, KIND_NAMES.get(it.kind, it.kind), content, to_mm(it.pos().x()), to_mm(it.pos().y()),
                     w, h, it.rotation(), det, it))
    return rows


def export_dimensions(doc, path, vars=None, author=""):
    s = build_scene(doc, vars)
    L = s.label
    wr = _pdf_writer(path, 297, 210)
    k = wr.resolution() / 25.4  # px strony na mm
    p = QPainter(wr)
    p.setRenderHint(QPainter.Antialiasing)

    # nagłówek
    f = QFont("Arial", 14, QFont.Bold)
    p.setFont(f)
    p.drawText(QRectF(15 * k, 10 * k, 267 * k, 10 * k), Qt.AlignLeft,
               f"Dokumentacja wymiarowa: {L.get('name', 'Etykieta')}")
    p.setFont(QFont("Arial", 9))
    p.drawText(QRectF(15 * k, 18 * k, 267 * k, 6 * k), Qt.AlignLeft,
               f"Format {fmt(L['w'])} × {fmt(L['h'])} mm, promień narożnika {fmt(L['radius'])} mm, "
               f"druk {s.print['dpi']} dpi · {datetime.date.today():%d.%m.%Y}"
               + (f" · {author}" if author else "") + " · wymiary w mm")

    # rysunek w skali
    area = QRectF(25 * k, 35 * k, 247 * k, 155 * k)
    scale = next((sc for sc in SCALES if L["w"] * sc * k <= area.width() and L["h"] * sc * k <= area.height()),
                 SCALES[-1])
    lw, lh = L["w"] * scale * k, L["h"] * scale * k
    origin = QPointF(area.x() + (area.width() - lw) / 2, area.y() + (area.height() - lh) / 2)
    target = QRectF(origin, QSizeF(lw, lh))
    p.save()
    p.setClipRect(target.adjusted(-1, -1, 1, 1))
    s.render(p, target, s.label_rect())
    p.restore()
    p.setPen(QPen(Qt.black, k * 0.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(target, L["radius"] * scale * k, L["radius"] * scale * k)
    p.setFont(QFont("Arial", 8))
    scale_txt = f"{scale:g}:1" if scale >= 1 else f"1:{1 / scale:g}"
    p.drawText(QRectF(15 * k, 195 * k, 100 * k, 6 * k), Qt.AlignLeft, f"Skala {scale_txt}")
    _dim(p, target.topLeft(), target.topRight(), -8 * k, fmt(L["w"]), k)
    _dim(p, target.topLeft(), target.bottomLeft(), -8 * k, fmt(L["h"]), k, vertical=True)

    # obrysy elementów z numerami i ich wymiary położenia
    sc = scale * k / mm(1)  # scena -> strona
    # tabela z wymiarów elementów; scena do druku ma teksty w powiększeniu ×8 (TextItem.hires)
    meta = build_scene(doc, vars, hires=False)  # zmienna trzyma scenę: bez niej Qt usuwa elementy z wierszy
    rows = item_rows(meta)
    for n, _, _, x, y, w, h, rot, _, it in rows:
        r = it.sceneBoundingRect()
        box = QRectF(origin.x() + r.x() * sc, origin.y() + r.y() * sc, r.width() * sc, r.height() * sc)
        p.setPen(QPen(QColor(0, 90, 200), k * 0.15, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 90, 200))
        c = box.topLeft() + QPointF(-2.2 * k, -2.2 * k)
        p.drawEllipse(c, 2 * k, 2 * k)
        p.setPen(Qt.white)
        p.setFont(QFont("Arial", 6, QFont.Bold))
        p.drawText(QRectF(c.x() - 2 * k, c.y() - 2 * k, 4 * k, 4 * k), Qt.AlignCenter, str(n))
    p.setFont(QFont("Arial", 7))

    # tabela na kolejnych stronach
    cells = "".join(
        f"<tr><td align=center>{n}</td><td>{html.escape(t)}</td><td>{html.escape(c[:80])}</td>"
        f"<td align=right>{fmt(x)}</td><td align=right>{fmt(y)}</td><td align=right>{fmt(w)}</td>"
        f"<td align=right>{fmt(h)}</td><td align=right>{rot:g}°</td>"
        f"<td>{html.escape(d).replace(chr(10), '<br>')}</td></tr>"
        for n, t, c, x, y, w, h, rot, d, _ in rows)
    td = QTextDocument()
    td.documentLayout().setPaintDevice(wr)
    td.setDefaultFont(QFont("Arial", 8))
    td.setDefaultStyleSheet("* { color: #000; }")  # nie z palety systemu (ciemny motyw)
    td.setHtml(
        "<h3>Wykaz elementów</h3><p>X, Y — położenie lewego górnego narożnika elementu (przed obrotem) "
        "od lewej górnej krawędzi etykiety. Wymiary w mm, czcionki w punktach typograficznych "
        "(1 pt = 0,353 mm).</p>"
        "<table border=1 cellspacing=0 cellpadding=3 width=100%>"
        "<tr bgcolor='#e8e8ee'><th>Nr</th><th>Typ</th><th>Zawartość</th><th>X</th><th>Y</th>"
        "<th>Szer.</th><th>Wys.</th><th>Obrót</th><th>Parametry</th></tr>" + cells + "</table>")
    page = QSizeF(267 * k, 190 * k)
    td.setPageSize(page)
    for i in range(td.pageCount()):
        wr.newPage()
        p.save()
        p.translate(15 * k, 10 * k - i * page.height())
        td.drawContents(p, QRectF(0, i * page.height(), page.width(), page.height()))
        p.restore()
    p.end()

"""Samotest bez okna: python selftest.py [katalog_wyników]"""
import base64
import datetime
import os
import sys
import zlib

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")  # offscreen nie ma czcionek
from PySide6.QtGui import QImage, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import output  # noqa: E402
from items import BarcodeItem, Code2DItem, LabelScene, ShapeItem, TextItem, mm, substitute, to_mm  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "."

# zmienne
now = datetime.datetime(2026, 1, 31, 8, 5)
v = {"LICZNIK": 42, "__now": now, "Partia": "A<1>"}
assert substitute("{DATA}|{DATA+1}|{CZAS}|{LICZNIK:5}|{Partia}|{X}", v) == "31.01.2026|01.02.2026|08:05|00042|A<1>|{X}"
assert substitute("{Partia}", v, escape=True) == "A&lt;1&gt;"

# dokument ze wszystkimi typami
s = LabelScene()
t = TextItem("Woda mineralna\nLOT {LICZNIK:4}")
t.setPos(mm(3), mm(3))
t.set("width", 50)
s.addItem(t)
b = BarcodeItem(); b.setPos(mm(3), mm(20)); s.addItem(b)
q = Code2DItem(); q.setPos(mm(70), mm(5)); s.addItem(q)
dm = Code2DItem(); dm.set("symbology", "GS1 DataMatrix"); dm.set("data", "(01)05901234123457(10)AB12"); dm.setPos(mm(55), mm(30)); s.addItem(dm)
for kind, x, y in (("rect", 72, 28), ("line", 3, 46), ("ellipse", 72, 40)):
    it = ShapeItem(kind); it.setPos(mm(x), mm(y)); s.addItem(it)
for z, it in enumerate(s.label_items()):
    it.setZValue(z)
assert b._error is None and q._error is None and dm._error is None, (b._error, q._error, dm._error)
assert abs(b.size_mm()[0] - (95 + 9) * 0.33) < 0.01  # EAN-13: 95 modułów + miejsce na 1. cyfrę

doc = s.to_doc()
import json  # noqa: E402
with open(os.path.join(out, "przyklad.etk"), "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=1)
s2 = LabelScene(); s2.load_doc(doc)
assert s2.to_doc() == doc, "zapis/odczyt nie jest zgodny"

# podstawienie w HTML
p = LabelScene(preview=True); p.load_doc(doc, v)
assert "LOT 0042" in [i for i in p.label_items() if isinstance(i, TextItem)][0].toPlainText()

# bity ZPL: czarny piksel (0,0) -> pierwszy bit 1, bity poza szerokością = 0
img = QImage(10, 2, QImage.Format_RGB32); img.fill(Qt.white); img.setPixel(0, 0, 0xFF000000)
img.setPixel(9, 1, 0xFF000000)
data, bpr = output.mono_bytes(img.convertToFormat(QImage.Format_Mono, Qt.ThresholdDither))
assert bpr == 2 and data == bytes([0x80, 0x00, 0x00, 0x40]), data.hex()

# ZPL: rozmiar, Z64 i CRC
pr = dict(doc["print"], method="zpl", dpi=203, orientation=180, columns=2, col_gap=3, offset_x=1, offset_y=-0.5)
doc["print"] = pr
zpl = output.build_zpl(doc, [v], 3)
assert zpl.startswith("^XA") and "^PQ3" in zpl and "^MMT" in zpl and "^LS0" in zpl and "^LT0" in zpl

# przesunięcie w układzie projektu: obraz z offsetem = obraz bez offsetu przesunięty o (dx, dy)
p0 = dict(doc["print"], method="tspl", dpi=300, orientation=0, columns=1, offset_x=0, offset_y=0)
a = output.roll_image(doc, v, p0)
b2 = output.roll_image(doc, v, dict(p0, offset_x=2, offset_y=3))
dx, dy = output.dots(2, 300), output.dots(3, 300)
assert a.copy(0, 0, a.width() - dx, a.height() - dy) == b2.copy(dx, dy, a.width() - dx, a.height() - dy)
# TSC, obrót 90°, w dół +2,5 mm (ustawienie z MH341): w poprzek głowicy SHIFT, obraz nieucięty
p90 = dict(p0, orientation=90)
base90 = output.roll_image(doc, v, p90)
size = output.windows_page_size(p90, doc["label"])
img90, size90, sx = output.tspl_image(doc, v, dict(p90, offset_y=2.5), size)
assert size90 == (50, 100) and img90 == base90 and sx == -output.dots(2.5, 300), (size90, sx)
assert output.tspl_image(doc, v, dict(p90, offset_y=40), size)[2] == -300  # SHIFT max 1 cal
# wzdłuż wysuwu (obrót 90°: przesunięcie w prawo) — w obrazie, bez SHIFT
img90x, _, sx0 = output.tspl_image(doc, v, dict(p90, offset_x=2), size)
assert sx0 == 0 and img90x.copy(0, output.dots(2, 300), 591, 100) == base90.copy(0, 0, 591, 100)
assert b"SHIFT -30,0" in output.build_tspl(dict(doc, print=dict(p90, offset_y=2.5)), [v], 1)
w = output.dots(100, 203) * 2 + output.dots(3, 203)
assert f"^PW{w}" in zpl, zpl[:200]
g = zpl.split(":Z64:")[1].split("^FS")[0]
b64, crc = g.rsplit(":", 1)
assert int(crc, 16) == output._crc16(b64.encode())
raw = zlib.decompress(base64.b64decode(b64))
assert len(raw) == ((w + 7) // 8) * output.dots(50, 203)
with open(os.path.join(out, "test.zpl"), "w") as fh:
    fh.write(zpl)

# TSPL: nagłówek, rozmiar bitmapy i odwrócone bity (0 = czarny)
tdoc = dict(doc, print=dict(pr, method="tspl", dpi=300, orientation=0, columns=1, offset_x=0, offset_y=0))
job = output.build_tspl(tdoc, [v], 2)
head, rest = job.split(b"BITMAP ", 1)
assert b"SIZE 100.00 mm,50.00 mm" in head and b"GAP 3.0 mm,0 mm" in head and b"SET TEAR ON" in head, head
assert b"SET REWIND OFF" in head
assert b"GAP 3.0 mm,0 mm" in output.build_tspl(dict(tdoc, print=dict(tdoc["print"], gap=0)), [v], 1)  # stare pliki
assert b"SET REWIND ON" in output.build_tspl(dict(tdoc, print=dict(tdoc["print"], mode="R")), [v], 1)
# obraz przesunięty w dół nie może być dłuższy niż etykieta
long_job = output.build_tspl(dict(tdoc, print=dict(tdoc["print"], offset_y=5)), [v], 1)
assert int(long_job.split(b"BITMAP ")[1].split(b",")[3]) == output.dots(50, 300)
x, y, bpr, hgt, mode, bits = rest.split(b",", 5)
assert (int(bpr), int(hgt)) == ((output.dots(100, 300) + 7) // 8, output.dots(50, 300))
assert bits.endswith(b"\r\nPRINT 1,2\r\n") and len(bits) == int(bpr) * int(hgt) + len(b"\r\nPRINT 1,2\r\n")
assert bits[0] == 0xFF  # lewy górny róg etykiety jest biały

# eksport plików
doc["print"] = dict(doc["print"], orientation=0, columns=1)
output.export_pdf(doc, os.path.join(out, "test.pdf"), v)
output.export_svg(doc, os.path.join(out, "test.svg"), v)
output.export_png(doc, os.path.join(out, "test.png"), 300, v)
output.export_dimensions(doc, os.path.join(out, "test-wymiary.pdf"), v, "test")
output.roll_image(doc, v, doc["print"]).save(os.path.join(out, "test-glowica.png"))
for f in ("test.pdf", "test.svg", "test.png", "test-wymiary.pdf"):
    assert os.path.getsize(os.path.join(out, f)) > 500, f
# zmiana rozmiaru uchwytami: każdy typ przelicza swoje parametry
r = ShapeItem("rect"); r.resize_to(30, 15); assert (r.w, r.h) == (30, 15)
eb = BarcodeItem(); eb.resize_to((95 + 9) * 0.4, None); assert eb.module == 0.4, eb.module
eb.resize_to(None, 20 + to_mm(eb._text_h())); assert abs(eb.bar_height - 20) < 1e-6
qq = Code2DItem(); qq.resize_to(len(qq._m[0]) * 0.6, None); assert qq.module == 0.6
tt = TextItem("abc"); tt.resize_to(37.04, None); assert tt.width == 37.0 and len(tt.handles()) == 6
st = tt.begin_resize(); tt.scale_fonts(st[0], st[1], 2.0)  # narożnik tekstu: czcionka × 2, szerokość × 2
assert tt.font_runs()[0][1] == 20 and tt.width == 74.0, (tt.font_runs(), tt.width)
assert set(ShapeItem("line").handles()) == {"l", "r"} and len(Code2DItem().handles()) == 4

# PDF417 i Aztec: obraz na 300 dpi odczytuje się jako ta sama treść
import numpy as np  # noqa: E402
import zxingcpp  # noqa: E402
s3 = LabelScene()
for kind, x in (("PDF417", 3), ("Aztec", 60)):
    c = Code2DItem(); c.set("symbology", kind); c.set("data", f"Ustronianka {kind} LOT {{LICZNIK:4}}")
    c.set("module", 0.34); c.setPos(mm(x), mm(5)); s3.addItem(c)
    assert c._error is None, c._error
im = output.render_image(s3.to_doc(), {"LICZNIK": 7}, 300).convertToFormat(QImage.Format_Grayscale8)
arr = np.frombuffer(bytes(im.constBits()), np.uint8).reshape(im.height(), im.bytesPerLine())[:, :im.width()]
got = sorted((r.format.name, r.text) for r in zxingcpp.read_barcodes(arr))
assert got == [("Aztec", "Ustronianka Aztec LOT 0007"), ("PDF417", "Ustronianka PDF417 LOT 0007")], got

# źródła danych: Excel (data, liczba całkowita, pusty wiersz) i baza SQLite przez QtSql
import openpyxl  # noqa: E402
import dialogs  # noqa: E402
xl = os.path.join(out, "dane.xlsx")
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["Produkt", "EAN", "Data"]); ws.append(["Woda 1,5 l", 5901234123457.0, datetime.date(2027, 3, 1)])
ws.append([None, None, None]); ws.append(["Woda 0,5 l", 5901234123464, None]); wb.save(xl)
assert dialogs.read_data_file(xl) == [{"Produkt": "Woda 1,5 l", "EAN": "5901234123457", "Data": "01.03.2027"},
                                      {"Produkt": "Woda 0,5 l", "EAN": "5901234123464", "Data": ""}]
dbp = os.path.join(out, "dane.db")
if os.path.exists(dbp):
    os.remove(dbp)
import sqlite3  # noqa: E402
with sqlite3.connect(dbp) as con:
    con.execute("CREATE TABLE p (Produkt TEXT, Partia INTEGER)"); con.execute("INSERT INTO p VALUES ('Woda', 42)")
con.close()
assert dialogs.read_sql(dbp, "SELECT Produkt, Partia FROM p") == [{"Produkt": "Woda", "Partia": "42"}]
try:
    dialogs.read_sql(dbp, "SELECT * FROM brak")
    raise AssertionError("błędne zapytanie powinno zgłosić błąd")
except ValueError as ex:
    assert "Błąd zapytania" in str(ex)
assert dialogs.has_password("DSN=x;UID=a;PWD=tajne") and not dialogs.has_password("DSN=x;Trusted_Connection=yes")

# druk: szerokość tekstu proporcjonalna do rozmiaru czcionki (Qt sam zaokrągla do pełnych px ekranu)
def text_width_mm(pt):
    sc = LabelScene(); tx = TextItem(""); tx.html = f'<p style="font-size:{pt}pt"><b>V-MAX SPORT IZOTONIK</b></p>'
    tx.setPos(mm(5), mm(5)); sc.addItem(tx)
    g = output.render_image(sc.to_doc(), {}, 300).convertToFormat(QImage.Format_Grayscale8)
    ar = np.frombuffer(bytes(g.constBits()), np.uint8).reshape(g.height(), g.bytesPerLine())[:, :g.width()] < 110
    xs = np.where(ar.any(axis=0))[0]
    return (xs.max() - xs.min()) * 25.4 / 300, xs.min() * 25.4 / 300
w70, x70 = text_width_mm(7.0); w75, x75 = text_width_mm(7.5)
assert abs(w75 / w70 - 7.5 / 7.0) < 0.01, (w70, w75)   # bez poprawki: 49,4 vs 55,0 mm (+11%)
assert abs(x70 - x75) < 0.15, (x70, x75)               # lewa krawędź stoi w miejscu
meta = output.build_scene(doc, v); rows = output.item_rows(meta)
assert any("Arial 10 pt" in r[8] for r in rows), [r[8] for r in rows]  # tabela wymiarów bez ×8

# skojarzenie .etk: tymczasowy klucz HKCU (prawdziwe skojarzenia nietknięte), udajemy zbudowany .exe
import subprocess  # noqa: E402
import winreg  # noqa: E402
import fileassoc  # noqa: E402
root = r"Software\EtykietyTestSkojarzenia\Classes"
real_exe, sys.frozen = sys.executable, True
try:
    sys.executable = r"C:\Program\ProjektantEtykiet.exe"
    assert fileassoc.ensure_registered(root) is True                     # brak wpisu -> zapis
    assert fileassoc.registered_command(root) == r'"C:\Program\ProjektantEtykiet.exe" "%1"'
    assert fileassoc.ensure_registered(root) is False                    # już dobrze -> nic
    sys.executable = r"D:\Nowe miejsce\ProjektantEtykiet.exe"
    assert fileassoc.ensure_registered(root) is True                     # przeniesiony -> poprawka
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + r"\.etk\OpenWithProgids") as k:
        assert winreg.QueryValueEx(k, fileassoc.PROG_ID)[0] == ""
finally:
    sys.executable, sys.frozen = real_exe, False
    del sys.frozen
    subprocess.run(["reg", "delete", r"HKCU\Software\EtykietyTestSkojarzenia", "/f"], capture_output=True)
assert fileassoc.registered_command(root) is None

# import .btw: sztuczny plik w układzie rozpoznanym w plikach BarTender 2022 (archiwum MFC w zlib)
import struct  # noqa: E402
import btw  # noqa: E402
from items import make_item  # noqa: E402


def cs(t):
    return b"\xff\xfe\xff" + bytes([len(t)]) + t.encode("utf-16-le")


logfont = struct.pack("<5i", -200, 0, 0, 0, 700) + bytes(8) + "Arial".encode("utf-16-le").ljust(64, b"\0")
stream = (cs("BarTender") + b"\xff\xff\x01\x00\x08\x00TextData" + struct.pack("<ii", 1378, 100) + bytes(12) + cs("")
          + cs("") + b"\x01" + cs("") + bytes(4) + cs("") + b"\x00\x01\x01" + bytes(21) + cs("Tekst 1") + bytes(16)
          + cs("(???) ???-????") + cs("")[:4] + b"\xff" * 4 + cs("Zażółć\rAla") + b"\x01" + cs("") + b"\xff\xff"
          + cs("") + b"\x00\x00" + logfont + b"\xff" * 8 + struct.pack("<4i", 0, 1, 0, 0))  # bez zawijania, środek
raw = (b"Bar Tender Format File\r\n<Metadata><TemplateSize>70 x 50 mm</TemplateSize></Metadata>\r\n"
       + zlib.compress(stream))
bdoc, bwarn = btw.Importer(raw).run()
assert (bdoc["label"]["w"], bdoc["label"]["h"]) == (70, 50) and not bwarn, bwarn
bt = make_item(bdoc["items"][0])
assert bt.content() == "Zażółć\nAla" and bt.align == "do środka", (bt.content(), bt.align)
assert abs(bt.get("x") + bt.size_mm()[0] / 2 - 35) < 0.05 and abs(bt.get("y") - 2.54) < 0.01  # zaczepienie: góra-środek
assert "font-weight:700" in bdoc["items"][0]["html"] and "10pt" in bdoc["items"][0]["html"]
# archiwum zgodne z BarTenderem 10.1 (ArchiveVersion 88634): nagłówek obiektu bez bajtu \x01
old_raw = raw.replace(zlib.compress(stream), zlib.compress(stream.replace(cs("") + cs("") + b"\x01", cs("") + cs(""), 1)))
assert make_item(btw.Importer(old_raw).run()[0]["items"][0]).content() == "Zażółć\nAla"
try:
    btw.Importer(b"to nie jest btw")
    raise AssertionError("brak błędu dla złego pliku")
except ValueError:
    pass


def roundtrip(doc, name):
    """Zapis .btw z wzoru i ponowny import."""
    p = os.path.join(out, name)
    notes = btw.write_btw(doc, p)
    return btw.read_btw(p)[0], notes


# zapis .btw: zmieniona treść i przesunięcie o 5 mm trafiają do wzoru, zaczepienie (góra-środek) zostaje
bt.setPlainText("Zażółć\nAla ma kota")
bt.setPos(bt.pos().x() + mm(5), bt.pos().y())
bdoc["items"][0] = bt.to_dict()
bdoc2, notes = roundtrip(bdoc, "test_zapis.btw")
bt2 = make_item(bdoc2["items"][0])
assert bt2.content() == "Zażółć\nAla ma kota" and not notes, (bt2.content(), notes)
assert abs(bt2.get("x") + bt2.size_mm()[0] / 2 - 40) < 0.05 and abs(bt2.get("y") - 2.54) < 0.01
assert btw._spread(["przez:", " Ustronianka\n"], "przez: Ustronianka i S-ka\n") == (["przez:", " Ustronianka i S-ka\n"], False)
assert btw._spread(["A", "B", "C"], "AXC") == (["AX", "", "C"], True)
sample_btw = os.path.join(os.path.dirname(__file__), "..", "..", "Etykiety", "V-MAX", "V-MAX Lemon.btw")
if os.path.exists(sample_btw):  # prawdziwy plik użytkownika (poza repozytorium)
    bdoc, bwarn = btw.read_btw(sample_btw)
    kinds = [i["kind"] for i in bdoc["items"]]
    assert kinds == ["text", "barcode", "text", "text", "text", "code2d"], kinds
    assert bdoc["items"][1]["data"] == "590224174580" and abs(bdoc["items"][1]["bar_height"] - 12.5) < 0.05
    assert bdoc["items"][5]["data"].startswith("https://grupaeurocash.pl")
    # bez zmian: te same dane po zapisie; po zmianach: nowy EAN, nowy QR (z sumą CRC), przesunięty QR
    same, notes = roundtrip(bdoc, "test_bez_zmian.btw")
    assert [i.get("data") for i in same["items"]] == [i.get("data") for i in bdoc["items"]] and not notes, notes
    bdoc["items"][1]["data"] = "590123412345"
    bdoc["items"][5]["data"] = "https://example.com/test-zapisu"
    bdoc["items"][5]["x"] += 2
    new, notes = roundtrip(bdoc, "test_zmiany.btw")
    assert new["items"][1]["data"] == "590123412345" and new["items"][5]["data"] == "https://example.com/test-zapisu"
    assert abs(new["items"][5]["x"] - bdoc["items"][5]["x"]) < 0.05 and not notes, notes

print("SELFTEST OK")

"""Test akceptacyjny na prawdziwej TSC: klika okna programu tak jak użytkownik.
Użycie: python acceptance.py [katalog_wyników]  — DRUKUJE 3 etykiety 70×50 i uruchamia kalibrację nośnika."""
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

import app as A
import dialogs
import output
import theme

out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
path = os.path.join(out, "akceptacja.etk")
qa = QApplication(sys.argv)
theme.apply_theme(qa)
A.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))  # zamiast okna wyboru pliku
log = []
if os.environ.get("DRY"):  # DRY=1: zadanie do pliku zamiast na drukarkę
    output.send_usb = lambda data, prefer="": (log.append(f"(na sucho) {len(data)} bajtów"),
                                               open(os.path.join(out, "akceptacja.prn"), "ab").write(
                                                   data if isinstance(data, bytes) else data.encode()))
w = A.MainWindow()
w.show()


def report():
    print("\n".join(log), flush=True)


def on_modal(fn, delay=400):
    """Wykonuje fn na oknie modalnym, które za chwilę się otworzy; błąd testu trafia do raportu."""
    def run():
        m = qa.activeModalWidget()
        try:
            fn(m)
        except Exception as ex:  # nie zostawiaj wiszącego okna ani cichego końca
            log.append(f"BŁĄD TESTU w {fn.__name__}: {ex!r}")
            if m is not None:
                m.reject()
    QTimer.singleShot(delay, run)


QTimer.singleShot(60000, lambda: (log.append("PRZERWANO: limit czasu 60 s"), report(), qa.exit(1)))


def button(dlg, text):
    return next(b for b in dlg.findChildren(QPushButton) if text in b.text())


# 1) Nowa etykieta: kafelek TSC, 70 × 50
def new_label(d):
    assert isinstance(d, dialogs.NewLabelDialog), d
    d.printer_btns["tsc"].click()
    next(b for b, w_, h_ in d.preset_btns if (w_, h_) == (70, 50)).click()  # kafelek rozmiaru po drukarce
    assert d.printer_btns["tsc"].isChecked(), "kafelek rozmiaru odznaczył drukarkę"
    assert (d.w.value(), d.h.value()) == (70, 50)
    d.w.setValue(71)  # własny rozmiar: żaden kafelek nie jest podświetlony
    assert not any(b.isChecked() for b, *_ in d.preset_btns)
    d.w.setValue(70)
    button(d, "Utwórz").click()


on_modal(new_label)
w.new_doc()
pr = w.scene.print
assert (pr["method"], pr["zpl_target"], pr["dpi"]) == ("tspl", "usb", 300), pr
log.append("nowa etykieta TSC 70×50: OK")


# 2) Ustawienia: obrót 90°, kalibracja nośnika, zapis
def settings(d):
    assert isinstance(d, dialogs.SettingsDialog), d
    d.orient.setCurrentIndex(d.orient.findData(90))
    on_modal(lambda m: (log.append("kalibracja: " + m.text()), m.accept()), 600)
    button(d, "Kalibruj").click()
    button(d, "Zapisz ustawienia").click()


on_modal(settings)
w.settings()
assert w.scene.print["orientation"] == 90

# 3) Elementy jak z przycisków paska „Wstaw”
w.add(A.ShapeItem("rect"))
fr = w.selected()[0]
for k, v in (("w", 66), ("h", 46), ("line", 0.4), ("x", 2), ("y", 2)):
    w.set_prop(fr, k, v)
w.add(A.TextItem("Test akceptacyjny nr {LICZNIK:3}"))
t = w.selected()[0]
for k, v in (("width", 60), ("align", "do środka"), ("x", 5), ("y", 4)):
    w.set_prop(t, k, v)
w.add(A.BarcodeItem())
b = w.selected()[0]
for k, v in (("bar_height", 15), ("x", 5), ("y", 13)):
    w.set_prop(b, k, v)
w.add(A.Code2DItem())
q = w.selected()[0]
for k, v in (("data", "https://ustronianka.pl"), ("x", 47), ("y", 11)):
    w.set_prop(q, k, v)
w.add(A.Code2DItem())
dm = w.selected()[0]
for k, v in (("symbology", "GS1 DataMatrix"), ("data", "(01)05901234123457(10)TEST{LICZNIK:3}"), ("x", 49),
             ("y", 30)):
    w.set_prop(dm, k, v)
assert all(i._error is None for i in (b, q, dm)), [i._error for i in (b, q, dm)]

# 4) Zapis, zamknięcie, ponowne otwarcie
assert w.save_doc() and os.path.exists(path)
before = w.doc()
w.new_doc(ask=False)
w.open_doc(path)
assert w.doc() == before, "po ponownym otwarciu projekt się różni"
log.append(f"zapis i ponowne otwarcie {path}: OK")


# 5) DRUKUJ: 3 kolejne numery, po 1 kopii
# okno błędu druku = wynik testu, nie sukces; przechwycone wprost, bez zgadywania kiedy się otworzy
dialogs.QMessageBox.critical = staticmethod(
    lambda parent, title, text: log.append(f"DRUKUJ: BŁĄD — {text}".replace("\n", " ")))


def do_print(d):
    assert isinstance(d, dialogs.PrintDialog), d
    d.count.setValue(3)
    d.copies.setValue(1)
    QTimer.singleShot(0, lambda: (button(d, "DRUKUJ").click(), d.isVisible() and d.reject()))


def print_then_check():
    try:
        before = len(log)
        on_modal(do_print)
        w.print_dialog()
        if not any(line.startswith(("DRUKUJ: BŁĄD", "BŁĄD TESTU")) for line in log[before:]):
            log.append("DRUKUJ: wysłano bez błędu 3 etykiety (nr 001–003)")
        # 6) Odczyt kodów programem z dokładnie tego obrazu, który dostała głowica
        import numpy as np
        import zxingcpp
        doc = w.doc()
        for n in (1, 2, 3):
            size = output.windows_page_size(doc["print"], doc["label"])
            img = output.tspl_image(doc, {"LICZNIK": n}, doc["print"], size)[0].convertToFormat(
                output.QImage.Format_Grayscale8)
            arr = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.bytesPerLine())
            found = sorted(f"{r.format.name}={r.text}" for r in zxingcpp.read_barcodes(arr[:, :img.width()]))
            log.append(f"etykieta {n}: " + "; ".join(found))
            img.save(os.path.join(out, f"akceptacja_glowica_{n}.png"))
    except Exception as ex:
        log.append(f"BŁĄD TESTU: {ex!r}")
    finally:
        report()
        qa.quit()


QTimer.singleShot(3000 if os.environ.get("DRY") else 10000, print_then_check)  # czas na kalibrację
qa.exec()

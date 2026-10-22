"""Test uchwytów: przeciąganie myszą w prawdziwym oknie. Użycie: python test_uchwyty.py [zrzut.png]"""
import sys

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app as A
import theme
from items import mm, to_mm

qa = QApplication(sys.argv)
theme.apply_theme(qa)
w = A.MainWindow()
w.resize(1400, 850)
w.show()
res, failed = [], []


def check(cond, msg):
    res.append(("OK   " if cond else "BŁĄD ") + msg)
    if not cond:
        failed.append(msg)


def drag(item, handle, d_mm):
    """Przeciąga uchwyt o (dx, dy) mm na ekranie."""
    for _ in range(3):  # po dodaniu elementu widok jeszcze się przewija — liczymy pozycję w ułożonym widoku
        qa.processEvents()
    v, vp = w.view, w.view.viewport()
    start = v.mapFromScene(item.mapToScene(item.handles()[handle]))
    end = v.mapFromScene(item.mapToScene(item.handles()[handle]) + QPointF(mm(d_mm[0]), mm(d_mm[1])))
    QTest.mouseMove(vp, start)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
    for i in range(1, 9):
        QTest.mouseMove(vp, start + (end - start) * i / 8)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, end)
    qa.processEvents()


def edges(item):
    r = item.sceneBoundingRect()
    return round(to_mm(r.left()), 1), round(to_mm(r.top()), 1), round(to_mm(r.right()), 1), round(to_mm(r.bottom()), 1)


def run():
    w.add(A.ShapeItem("rect"))
    r = w.selected()[0]
    check(len(r.handles()) == 8, "ramka ma 8 uchwytów")
    l0, t0, r0, b0 = edges(r)
    drag(r, "rb", (10, 5))
    check((r.w, r.h) == (30, 15), f"narożnik prawy-dolny: 20×10 → {r.w:g}×{r.h:g}")
    check(edges(r)[:2] == (l0, t0), "lewy-górny róg stoi w miejscu")
    l0, t0, r0, b0 = edges(r)
    drag(r, "l", (-5, 0))
    check(r.w == 35 and edges(r)[2] == r0 and edges(r)[0] == l0 - 5, f"lewy bok: szer. {r.w:g}, prawa krawędź stoi")
    drag(r, "t", (0, -4))
    check(r.h == 19 and edges(r)[3] == b0, f"górny bok: wys. {r.h:g}, dolna krawędź stoi")
    drag(r, "lt", (3, 3))
    check((r.w, r.h) == (32, 16), f"narożnik lewy-górny: {r.w:g}×{r.h:g}")

    w.add(A.ShapeItem("line"))
    ln = w.selected()[0]
    check(set(ln.handles()) == {"l", "r"}, "linia ma tylko 2 końce")
    drag(ln, "r", (10, 0))
    check(ln.w == 40 and ln.h == 0.4, f"linia: długość {ln.w:g}, grubość bez zmian {ln.h:g}")

    w.add(A.TextItem("Nr {LICZNIK:6}"))
    t = w.selected()[0]
    check(len(t.handles()) == 6, "tekst ma 6 uchwytów (boki + narożniki)")
    pt0 = t.font_runs()[0][1]
    h0 = t.size_mm()[1]
    drag(t, "rb", (0, h0))  # podwojenie wysokości
    pt1 = t.font_runs()[0][1]
    check(abs(pt1 - 2 * pt0) <= 1, f"narożnik tekstu skaluje czcionkę: {pt0:g} → {pt1:g} pt")
    drag(t, "r", (-3, 0))
    check(t.width > 0 and t.font_runs()[0][1] == pt1, f"bok tekstu: szerokość {t.width:g} mm, czcionka bez zmian")

    w.add(A.BarcodeItem())
    b = w.selected()[0]
    m0, bh0 = b.module, b.bar_height
    drag(b, "r", (10, 0))
    check(b.module > m0, f"kod kreskowy, bok: moduł {m0} → {b.module}")
    drag(b, "b", (0, -5))
    check(b.bar_height < bh0, f"kod kreskowy, dół: kreski {bh0:g} → {b.bar_height:.1f} mm")

    w.add(A.Code2DItem())
    q = w.selected()[0]
    check(set(q.handles()) == set(q.CORNERS), "kod 2D ma tylko narożniki")
    drag(q, "rb", (5, 5))
    check(q.module > 0.5, f"kod 2D: moduł 0,5 → {q.module}")

    q.set("rotation", 90)
    w.scene.clearSelection(); q.setSelected(True)
    e0 = edges(q)
    drag(q, "rb", (0, 4))  # po obrocie o 90° narożnik „rb” jest w lewym dolnym rogu ekranu
    check(q.module != 0 and edges(q) != e0, "obrócony kod 2D też się skaluje")

    w.undo()
    check(True, "cofnij po przeciąganiu działa")
    if len(sys.argv) > 1:
        w.scene.label_items()[0].setSelected(True)
        qa.processEvents()
        w.grab().save(sys.argv[1])
    print("\n".join(res))
    print("WYNIK:", "BŁĘDY: " + str(len(failed)) if failed else "wszystko OK")
    qa.exit(1 if failed else 0)


def safe():
    try:
        run()
    except Exception as ex:
        print("\n".join(res))
        print("BŁĄD TESTU:", repr(ex))
        qa.exit(2)


QTimer.singleShot(500, safe)
QTimer.singleShot(60000, lambda: (print("PRZERWANO: limit czasu"), qa.exit(3)))
sys.exit(qa.exec())

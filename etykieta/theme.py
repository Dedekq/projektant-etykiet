"""Jasny, kolorowy wygląd i ikony (Material Design przez qtawesome)."""
import os
import tempfile

os.environ.setdefault("QT_API", "pyside6")
import qtawesome as qta  # noqa: E402
from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate  # noqa: E402


class _ComboFix(QObject):
    """Domyślny delegat list rozwijanych rysuje podświetloną pozycję stylem samego pola (biały tekst na białym);
    QStyledItemDelegate respektuje reguły ::item z arkusza stylów."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Polish and isinstance(obj, QComboBox) \
                and not isinstance(obj.itemDelegate(), QStyledItemDelegate):
            obj.setItemDelegate(QStyledItemDelegate(obj))
        return False

# kolory grup przycisków
BLUE, GREEN, ORANGE, PURPLE, RED, TEAL, PINK, GRAY = (
    "#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#e53935", "#00897b", "#d81b60", "#546e7a")

# typ elementu -> (ikona, kolor, nazwa)
KIND_STYLE = {
    "text": ("format-text", BLUE, "Tekst"),
    "barcode": ("barcode", GREEN, "Kod kreskowy"),
    "code2d": ("qrcode", PURPLE, "Kod QR / DataMatrix"),
    "line": ("vector-line", ORANGE, "Linia"),
    "rect": ("rectangle-outline", ORANGE, "Prostokąt"),
    "ellipse": ("ellipse-outline", ORANGE, "Elipsa"),
    "image": ("image", PINK, "Obraz"),
}


def icon(name, color=GRAY):
    return qta.icon("mdi6." + name, color=color, color_disabled="#c0c4cc")


STYLE = """
QMainWindow, QDialog { background: #f4f6fb; }
QToolBar { background: #ffffff; border: none; border-bottom: 1px solid #e1e5ee; padding: 4px; spacing: 4px; }
QToolBar#insert { border-bottom: none; border-right: 1px solid #e1e5ee; }
QToolButton { border-radius: 8px; padding: 4px 6px; color: #263238; font-size: 9pt; }
QToolButton:hover { background: #e3f2fd; }
QToolButton:pressed, QToolButton:checked { background: #bbdefb; }
QToolButton#print { background: #e53935; color: white; font-weight: bold; padding: 4px 14px; }
QToolButton#print:hover { background: #c62828; }
QMenuBar { background: #ffffff; }
QMenu { background: #ffffff; border: 1px solid #d5dae5; padding: 4px; }
QMenu::item { padding: 6px 24px 6px 10px; border-radius: 4px; }
QMenu::item:selected { background: #e3f2fd; color: #0d47a1; }
QDockWidget::title { background: #1e88e5; color: white; padding: 6px; font-weight: bold; }
QStatusBar { background: #ffffff; border-top: 1px solid #e1e5ee; }
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox, QPlainTextEdit, QFontComboBox, QDateEdit {
    background: white; border: 1px solid #c5cbd8; border-radius: 6px; padding: 4px; min-height: 22px; }
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border: 2px solid #1e88e5; }
QPushButton { background: #1e88e5; color: white; border: none; border-radius: 8px; padding: 8px 16px;
    font-weight: bold; }
QPushButton:hover { background: #1565c0; }
QPushButton#secondary { background: #e3e7ef; color: #263238; }
QPushButton#secondary:hover { background: #cfd6e3; }
QPushButton#danger { background: #e53935; }
QPushButton#preset { background: white; color: #263238; border: 2px solid #d5dae5; padding: 10px; }
QPushButton#preset:hover { border-color: #1e88e5; }
QPushButton#preset:checked { border-color: #1e88e5; background: #e3f2fd; }
QTabWidget::pane { border: 1px solid #d5dae5; border-radius: 8px; background: white; }
QTabBar::tab { padding: 8px 14px; background: #e3e7ef; border-top-left-radius: 8px; border-top-right-radius: 8px;
    margin-right: 2px; }
QTabBar::tab:selected { background: #1e88e5; color: white; }
QLabel#hint { color: #546e7a; background: #fff8e1; border: 1px solid #ffe082; border-radius: 8px; padding: 8px; }
QFrame#card { background: white; border: 1px solid #e1e5ee; border-radius: 10px; }
"""


def _arrow_files():
    """Strzałki spinboxów i znaczek checkboxa jako pliki PNG — arkusz stylów przyjmuje tylko ścieżki."""
    d = os.path.join(tempfile.gettempdir(), "projektant_etykiet_ikony")
    os.makedirs(d, exist_ok=True)
    files = {}
    for key, name, color in (("up", "chevron-up", BLUE), ("down", "chevron-down", BLUE),
                             ("check", "check-bold", "white")):
        path = os.path.join(d, key + ".png")
        icon(name, color).pixmap(32, 32).save(path)
        files[key] = path.replace("\\", "/")
    return files


def apply_theme(app):
    """Zawsze jasny motyw — etykieta to biały papier, ciemny motyw systemu tylko by przeszkadzał."""
    app.setStyle("Fusion")
    p = QPalette()
    for role, c in ((QPalette.Window, "#f4f6fb"), (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, "#f4f6fb"),
                    (QPalette.Text, "#263238"), (QPalette.WindowText, "#263238"), (QPalette.Button, "#ffffff"),
                    (QPalette.ButtonText, "#263238"), (QPalette.Highlight, "#1e88e5"),
                    (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#fffde7"),
                    (QPalette.ToolTipText, "#263238"), (QPalette.PlaceholderText, "#90a4ae")):
        p.setColor(role, QColor(c))
    app.setPalette(p)
    app._combo_fix = _ComboFix(app)  # referencja, żeby filtr nie został usunięty
    app.installEventFilter(app._combo_fix)
    f = _arrow_files()
    app.setStyleSheet(STYLE + f"""
QAbstractSpinBox {{ padding-right: 24px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 22px; border: none; background: #e3f2fd;
    subcontrol-origin: border; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #bbdefb; }}
QAbstractSpinBox::up-arrow {{ image: url({f['up']}); width: 14px; height: 14px; }}
QAbstractSpinBox::down-arrow {{ image: url({f['down']}); width: 14px; height: 14px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({f['down']}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: white; color: #263238; border: 1px solid #c5cbd8; outline: none;
    selection-background-color: #1e88e5; selection-color: white; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 6px; border: none; }}
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{
    background: #1e88e5; color: white; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; border: 2px solid #90a4ae;
    background: white; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 11px; }}
QCheckBox::indicator:checked {{ background: #1e88e5; border-color: #1e88e5; image: url({f['check']}); }}
QRadioButton::indicator:checked {{ border-color: #1e88e5; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #1e88e5, stop:0.55 #1e88e5, stop:0.65 white, stop:1 white); }}
""")

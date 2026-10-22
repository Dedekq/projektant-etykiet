"""Skojarzenie plików .etk z programem — tylko dla bieżącego użytkownika (HKCU), bez uprawnień administratora."""
import ctypes
import os
import sys
import winreg

PROG_ID = "ProjektantEtykiet.etk"


def open_command():
    """Polecenie otwierania: zbudowany .exe albo (z kodu źródłowego) python + app.py."""
    if getattr(sys, "frozen", False):
        return sys.executable, f'"{sys.executable}" "%1"'
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py"))
    return sys.executable, f'"{sys.executable}" "{script}" "%1"'


def register(root=r"Software\Classes"):
    """Zapisuje .etk → ProjektantEtykiet.etk → polecenie otwarcia. root zmienia się tylko w teście."""
    icon_exe, cmd = open_command()
    values = {
        rf"{root}\.etk": PROG_ID,
        rf"{root}\{PROG_ID}": "Etykieta (Projektant etykiet)",
        rf"{root}\{PROG_ID}\DefaultIcon": f'"{icon_exe}",0',
        rf"{root}\{PROG_ID}\shell\open\command": cmd,
    }
    for key, value in values.items():
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)
    if root == r"Software\Classes":
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED: odśwież ikony
    return cmd


def registered_command(root=r"Software\Classes"):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\{PROG_ID}\shell\open\command") as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None

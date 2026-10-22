"""Kodowanie symboli: kody 1D (python-barcode), QR (segno), DataMatrix (pystrich)."""
import re

import barcode
import segno
from pystrich.datamatrix import FNC1, DataMatrixData, DataMatrixEncoder

BARCODE_TYPES = {
    "EAN-13": "ean13-guard",
    "EAN-8": "ean8-guard",
    "UPC-A": "upca",
    "EAN-14": "ean14",
    "Code 128": "code128",
    "GS1-128": "gs1_128",
    "Code 39": "code39",
    "ITF": "itf",
    "Codabar": "codabar",
}

# Nominalny moduł EAN (100% powiększenia) wg GS1
EAN_NOMINAL_MODULE_MM = 0.330


def barcode_modules(kind, data):
    """Zwraca (wzór modułów, tekst czytelny). Wzór: '1' kreska, '0' przerwa, 'G' kreska wydłużona (guard)."""
    cls = barcode.get_barcode_class(BARCODE_TYPES[kind])
    b = cls(data, add_checksum=False) if kind == "Code 39" else cls(data)
    return b.build()[0], b.get_fullcode()


def qr_matrix(data, ecc="M", micro=False):
    """Zwraca (macierz bool, wersja). Pusta treść = błąd."""
    if not data:
        raise ValueError("Pusta treść kodu QR")
    q = segno.make(data, error=ecc, micro=micro, boost_error=False)
    return [[bool(c) for c in row] for row in q.matrix], str(q.version)


# AI GS1 o stałej długości: po nich nie wstawia się separatora FNC1
_GS1_FIXED = ("00", "01", "02", "03", "04", "11", "12", "13", "14", "15", "16", "17",
              "18", "19", "20", "31", "32", "33", "34", "35", "36", "41")


def _gs1_segments(text):
    parts = re.findall(r"\((\d{2,4})\)([^(]*)", text)
    if not parts:
        raise ValueError("GS1: podaj dane w formacie (01)05901234123457(10)PARTIA")
    segs = [FNC1]
    for i, (ai, val) in enumerate(parts):
        segs.append(ai + val)
        if i < len(parts) - 1 and not ai.startswith(_GS1_FIXED):
            segs.append(FNC1)
    return DataMatrixData(*segs, encoding="ascii")


def datamatrix_matrix(data, gs1=False):
    """Zwraca (macierz bool, 'WxH')."""
    if not data:
        raise ValueError("Pusta treść DataMatrix")
    payload = _gs1_segments(data) if gs1 else DataMatrixData(data, auto_encoding=True)
    marks = DataMatrixEncoder(payload, quiet_zone=0).get_rect_marks()
    m = [[False] * marks.width for _ in range(marks.height)]
    for x, y, w, h in marks.marks:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                m[yy][xx] = True
    return m, f"{marks.width}x{marks.height}"

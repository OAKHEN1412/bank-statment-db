"""
ocr_engine.py — OCR pipeline for image-scanned bank statement PDFs.

Uses pypdfium2 (already installed with pdfplumber) to render pages to images,
then EasyOCR (Thai + English) to extract text, and reconstructs text lines
from bounding boxes.
"""

import re
import threading
import numpy as np

_reader = None
_lock = threading.Lock()


def _get_reader():
    """Lazy-load EasyOCR reader. Downloads models on first call (~100 MB)."""
    global _reader
    if _reader is None:
        with _lock:
            if _reader is None:
                import easyocr
                _reader = easyocr.Reader(['th', 'en'], gpu=False, verbose=False)
    return _reader


def has_text_layer(filepath: str, min_words: int = 30) -> bool:
    """
    Return True if the PDF has enough extractable text.
    Scanned (image-only) PDFs typically return 0-5 words.
    """
    try:
        import pdfplumber
        total = 0
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages[:3]:
                t = page.extract_text() or ''
                total += len(t.split())
                if total >= min_words:
                    return True
        return False
    except Exception:
        return False


def _render_pages(filepath: str, scale: int = 4):
    """
    Yield (page_idx, PIL.Image) for each page.
    scale=4 → ~288 DPI (72 * 4) — good quality without being too slow.
    """
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(filepath)
    try:
        for i in range(len(doc)):
            bitmap = doc[i].render(scale=scale)
            yield i, bitmap.to_pil()
    finally:
        doc.close()


def _reconstruct_lines(ocr_result, y_tol: int = 18) -> list:
    """
    Group EasyOCR detections into text lines (left→right, top→bottom).
    ocr_result: list of ([[x1,y1],[x2,y2],[x3,y3],[x4,y4]], text, confidence)
    y_tol: max vertical pixel distance to be considered the same line.
    """
    items = []
    for bbox, text, conf in ocr_result:
        if conf < 0.25 or not text.strip():
            continue
        x = min(pt[0] for pt in bbox)
        y = min(pt[1] for pt in bbox)
        items.append((y, x, text.strip()))

    if not items:
        return []

    items.sort()  # sort by (y, x)

    lines, cur = [], [items[0]]
    for item in items[1:]:
        if abs(item[0] - cur[0][0]) <= y_tol:
            cur.append(item)
        else:
            cur.sort(key=lambda t: t[1])
            lines.append(' '.join(t[2] for t in cur))
            cur = [item]
    cur.sort(key=lambda t: t[1])
    lines.append(' '.join(t[2] for t in cur))

    return lines


def normalize_amounts(text: str) -> str:
    """
    Fix common OCR errors in numeric amounts before regex parsing:
      - l / I / | in digit context → 1
      - O in digit context → 0
      - 1.780.48 → 1,780.48  (double-period: first = thousands separator)
      - 1,780,48 → 1,780.48  (comma as decimal separator)
    """
    # Replace look-alike characters inside digit runs
    text = re.sub(r'(?<=\d)[lI|](?=\d)', '1', text)
    text = re.sub(r'(?<=\d)O(?=\d)', '0', text)

    # Fix double-period amounts: 1.234.56 → 1,234.56
    def fix_double_period(m):
        s = m.group(0)
        parts = s.split('.')
        if len(parts) == 3 and len(parts[1]) == 3:
            return f'{parts[0]},{parts[1]}.{parts[2]}'
        return s

    text = re.sub(r'\d+\.\d{3}\.\d{2}', fix_double_period, text)

    # Fix European format: 22.808,85 → 22,808.85 (period=thousands, comma=decimal)
    def fix_european(m):
        s = m.group(0)
        # Replace the single period with comma, and the trailing comma with period
        return s.replace('.', ',').replace(',', '.', 1).replace('.', ',', 1)

    # Pattern: digits . 3digits , 2digits
    text = re.sub(
        r'\d+\.\d{3},\d{2}(?!\d)',
        lambda m: m.group(0).replace('.', '\x00').replace(',', '.').replace('\x00', ','),
        text,
    )

    # Fix comma-as-decimal: 1,780,48 → 1,780.48
    def fix_comma_decimal(m):
        s = m.group(0)
        parts = s.rsplit(',', 1)
        if len(parts) == 2 and len(parts[1]) == 2:
            return f'{parts[0]}.{parts[1]}'
        return s

    text = re.sub(r'\d[\d,]+,\d{2}(?!\d)', fix_comma_decimal, text)

    return text


def ocr_pdf_to_text(filepath: str, scale: int = 4) -> str:
    """
    Run EasyOCR on every page of a PDF and return reconstructed text.
    Pages are separated by blank lines.

    First call will download EasyOCR models (~100 MB for Thai+English)
    and may take 30–60 seconds. Subsequent calls are faster.
    """
    reader = _get_reader()
    all_lines = []
    for _page_num, img in _render_pages(filepath, scale=scale):
        result = reader.readtext(np.array(img), paragraph=False, detail=1)
        lines = _reconstruct_lines(result)
        all_lines.extend(lines)
        all_lines.append('')  # page boundary
    return '\n'.join(all_lines)

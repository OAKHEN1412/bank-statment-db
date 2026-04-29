import re
import pdfplumber
from datetime import datetime


def _parse_amount(s):
    return float(s.replace(',', ''))


def _convert_date(date_str):
    """DD/MM/YY where YY is CE year (25 -> 2025, 26 -> 2026)"""
    parts = date_str.split('/')
    if len(parts) != 3:
        return None
    day, mon, yr = parts
    year = int(yr) + 2000
    try:
        return datetime(year, int(mon), int(day)).strftime('%Y-%m-%d')
    except ValueError:
        return None


_DEBIT_CODES = {'X2', 'TX'}


# ---------------------------------------------------------------------------
# Standard format parser
# ---------------------------------------------------------------------------

def _parse_line(line):
    """
    Normal SCB: DD/MM/YY HH:MM CODE CHANNEL AMOUNT BALANCE[DESC]
    Debit codes: X2, TX.  Description may touch balance with no space.
    """
    m = re.match(
        r'(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2})\s+'
        r'([A-Z][A-Z0-9]*)\s+([A-Z]+)\s+'
        r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})(.*)',
        line
    )
    if not m:
        return None
    date_str, time_str, code, channel, amt_str, bal_str, desc_raw = m.groups()
    date = _convert_date(date_str)
    if not date:
        return None
    try:
        amount = _parse_amount(amt_str)
        balance = _parse_amount(bal_str)
    except ValueError:
        return None
    desc = f'{code} {channel} {desc_raw.strip()}'.strip()
    debit = amount if code in _DEBIT_CODES else 0.0
    credit = 0.0 if code in _DEBIT_CODES else amount
    return {'date': date, 'time': time_str, 'description': desc,
            'debit': debit, 'credit': credit, 'balance': balance}


# ---------------------------------------------------------------------------
# CID-encoded font decoder  (SCB Bank Feb format with broken ToUnicode)
# Digits/separators are remapped to other ASCII chars in the custom font.
# Mapping derived by comparing known date ranges and amounts across files.
# ---------------------------------------------------------------------------

# (cid:N) replacements — use control-char placeholders for letters that
# conflict with the ASCII digit map (M=8, L=4) so they survive the second pass.
_CID_MAP_V1 = {
    135: ':',     # time colon
    136: 'X',     # letter X  (X1 / X2 codes)
    137: ',',     # thousands separator
    138: '9',     # digit 9
    139: '\x01',  # placeholder → letter M  (BCMS channel)
    140: '\x02',  # placeholder → letter L  (TELL channel)
    141: 'E',     # letter E  (ENET channel)
    14:  '',      # noise / separator
}

# Some SCB Feb PDFs (page 2+) use a variant where 135↔137 and 136↔138 are swapped
_CID_MAP_V2 = {
    135: ',',     # thousands separator  (swapped vs V1)
    136: '9',     # digit 9              (swapped vs V1)
    137: ':',     # time colon           (swapped vs V1)
    138: 'X',     # letter X             (swapped vs V1)
    139: '\x01',
    140: '\x02',
    141: 'E',
    14:  '',
}

# Mis-mapped ASCII chars → their real characters
_CID_ASCII_MAP = str.maketrans({
    'i': '/',   # date slash
    'j': '.',   # decimal point
    'k': '7',   # digit 7
    't': '0',   # digit 0
    'u': 'T',   # letter T  (TELL / ATS)
    'w': 'A',   # letter A  (ATS)
    'x': 'N',   # letter N  (ENET)
    'K': '3',   # digit 3
    'L': '4',   # digit 4
    'M': '8',   # digit 8
    'O': '2',   # digit 2
    'P': '1',   # digit 1
    'Q': '5',   # digit 5
    'R': '6',   # digit 6
    '}': 'S',   # letter S  (ATS / BCMS)
    '|': 'B',   # letter B  (BCMS)
    '~': 'C',   # letter C  (BCMS)
    '\u00a4': 'I',  # ¤ → I   (IN code)
})


def _make_cid_decoder(cid_map):
    """Return a decode function for the given CID map."""
    def _decode(line):
        def _replace(m):
            return cid_map.get(int(m.group(1)), '')
        decoded = re.sub(r'\(cid:(\d+)\)', _replace, line)
        decoded = decoded.translate(_CID_ASCII_MAP)
        return decoded.replace('\x01', 'M').replace('\x02', 'L')
    return _decode


_decode_cid_v1 = _make_cid_decoder(_CID_MAP_V1)
_decode_cid_v2 = _make_cid_decoder(_CID_MAP_V2)


def _decode_cid_line(line, v2=False):
    return _decode_cid_v2(line) if v2 else _decode_cid_v1(line)


def _is_cid_v2(text):
    """Return True if this page uses V2 CID encoding (cid:138=X for codes).
    Compare frequency: V1 uses (cid:136)P/O for codes, V2 uses (cid:138)P/O."""
    v1_codes = len(re.findall(r'\(cid:136\)[PO] ', text))
    v2_codes = len(re.findall(r'\(cid:138\)[PO] ', text))
    return v2_codes > v1_codes


def _parse_line_cid(line, v2=False):
    """Parse a CID-encoded SCB line by decoding the custom font first."""
    decoded = _decode_cid_line(line, v2=v2)
    # Date and time may be adjacent (no space between year and hour)
    m = re.match(
        r'(\d{2}/\d{2}/\d{2})\s*(\d{2}:\d{2})\s+'
        r'([A-Z][A-Z0-9]*)\s+([A-Z]+)\s+'
        r'([\d,]+\.\d+)\s+([\d,]+\.\d+)',
        decoded
    )
    if not m:
        return None
    date_str, time_str, code, channel, amt_str, bal_str = m.groups()
    date = _convert_date(date_str)
    if not date:
        return None
    try:
        amount = _parse_amount(amt_str)
        balance = _parse_amount(bal_str)
    except ValueError:
        return None
    if amount <= 0:
        return None
    desc = f'{code} {channel}'
    debit = amount if code in _DEBIT_CODES else 0.0
    credit = 0.0 if code in _DEBIT_CODES else amount
    return {'date': date, 'time': time_str, 'description': desc,
            'debit': debit, 'credit': credit, 'balance': balance}


# ---------------------------------------------------------------------------
# OCR / scanned format parser  (e.g. SCB.pdf — camera/scanner with noise)
# Characteristics: pipe separators, HH.MM time, %2 for X2, etc.
# ---------------------------------------------------------------------------

def _clean_ocr_amount(s):
    """Fix common OCR corruptions in amount strings."""
    s = re.sub(r'[^0-9,.]', '', s)
    # "7.,969.06" → "7,969.06"  (spurious dot before comma)
    s = re.sub(r'(\d)\.,', r'\1,', s)
    # "1.107.79" → "1,107.79"  (dot used as thousands separator)
    m2 = re.match(r'^(\d+)\.(\d{3})\.(\d{2})$', s)
    if m2:
        return f'{m2.group(1)},{m2.group(2)}.{m2.group(3)}'
    return s


def _parse_line_ocr(line):
    """
    OCR-scanned SCB: date visible but noise around separators.
    Handles: |HH:MM|, HH.MM, HHMM, %2→X2, )|[ after amounts.
    """
    m = re.match(
        r'(\d{2}/\d{2}/\d{2})'          # date
        r'[^0-9]*'                        # noise / separator
        r'(\d{2}[:.]\d{2}|\d{4})'        # time: HH:MM, HH.MM, or HHMM
        r'\s*[|]?\s*'
        r'([>()%A-Z][>()%A-Z0-9]{0,3})'  # code (may have OCR prefix noise)
        r'\s+([A-Z]{2,6})\s+'            # channel
        r'([\d,.]+\.\d{1,2})'            # amount
        r'[^0-9]*'                        # noise after amount
        r'\s*([\d,.]+\.\d{1,2})(.*)',    # balance + description
        line
    )
    if not m:
        return None
    date_str, time_str, code, channel, amt_str, bal_str, desc_raw = m.groups()

    # Normalise time
    if ':' not in time_str:
        if '.' in time_str:
            time_str = time_str.replace('.', ':')
        elif len(time_str) == 4 and time_str.isdigit():
            time_str = time_str[:2] + ':' + time_str[2:]

    # Normalise code: strip leading OCR noise, % → X, take first 2 chars
    code = re.sub(r'^[>()\s]+', '', code)
    code = code.replace('%', 'X')
    if len(code) > 2 and code[0].isalpha() and (code[1].isalpha() or code[1].isdigit()):
        code = code[:2]

    amt_str = _clean_ocr_amount(amt_str)
    bal_str = _clean_ocr_amount(bal_str)

    date = _convert_date(date_str)
    if not date:
        return None
    try:
        amount = _parse_amount(amt_str)
        balance = _parse_amount(bal_str)
    except ValueError:
        return None
    if amount <= 0:
        return None

    desc = f'{code} {channel} {desc_raw.strip()}'.strip()
    debit = amount if code in _DEBIT_CODES else 0.0
    credit = 0.0 if code in _DEBIT_CODES else amount
    return {'date': date, 'time': time_str, 'description': desc,
            'debit': debit, 'credit': credit, 'balance': balance}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse(filepath):
    """
    Parse all pages of an SCB PDF.
    Auto-detects format: standard | CID-encoded font | OCR-scanned.
    Debit codes: X2, TX — all others are credit.
    """
    transactions = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            # Detect format from the density of (cid:N) sequences
            is_cid = text.count('(cid:') > 5
            v2 = is_cid and _is_cid_v2(text)
            for line in text.split('\n'):
                if is_cid:
                    row = _parse_line_cid(line, v2=v2)
                else:
                    row = _parse_line(line)
                    if row is None:
                        row = _parse_line_ocr(line)
                if row:
                    transactions.append(row)
    return transactions


def _parse_text_block(text: str) -> list:
    return [row for line in text.split('\n')
            for row in [_parse_line(line)] if row]


def parse_from_text(text: str) -> list:
    """Parse from OCR-extracted text."""
    from ocr_engine import normalize_amounts
    return _parse_text_block(normalize_amounts(text))

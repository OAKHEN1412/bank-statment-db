import re
import pdfplumber
from datetime import datetime


DEBIT_KEYWORDS = ['Transfer out', 'Billpayment', 'Payment', 'ถอน', 'โอนออก']
CREDIT_KEYWORDS = ['Transfer in', 'รับโอน', 'ฝาก', 'โอนเข้า']


def _strip_cid(text):
    """Remove (cid:XXX) font artifacts from TTB PDFs."""
    return re.sub(r'\(cid:\d+\)', '', text)


def _parse_amount(s):
    return float(s.replace(',', ''))


def _is_debit(line):
    for kw in DEBIT_KEYWORDS:
        if kw.lower() in line.lower():
            return True
    return False


def _is_credit(line):
    for kw in CREDIT_KEYWORDS:
        if kw.lower() in line.lower():
            return True
    return False


def parse(filepath):
    """
    TTB format:
    DD.MM.YYYY HH:MM:SS CHANNEL DESCRIPTION AMOUNT BALANCE
    'Transfer out' / 'Billpayment' = debit
    'Transfer in' = credit
    TTB PDFs contain (cid:XXX) artifacts that must be stripped.
    """
    transactions = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            raw = page.extract_text()
            if not raw:
                continue
            text = _strip_cid(raw)
            for line in text.split('\n'):
                # Must start with DD.MM.YYYY HH:MM:SS
                m = re.match(
                    r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.*)',
                    line
                )
                if not m:
                    continue
                date_str, time_str, rest = m.groups()
                # Skip opening/closing balance lines
                if 'ยอดคงเหลือยกมา' in rest or 'ยอดยกมา' in rest:
                    continue
                amounts = re.findall(r'[\d,]+\.\d{2}', rest)
                if len(amounts) < 2:
                    continue
                try:
                    amount = _parse_amount(amounts[-2])
                    balance = _parse_amount(amounts[-1])
                except (ValueError, IndexError):
                    continue
                try:
                    dt = datetime.strptime(date_str, '%d.%m.%Y')
                    date = dt.strftime('%Y-%m-%d')
                except ValueError:
                    continue
                # Determine debit/credit
                if _is_debit(rest):
                    debit = amount
                    credit = 0.0
                elif _is_credit(rest):
                    debit = 0.0
                    credit = amount
                else:
                    # Fallback: check if balance went up or down (not reliable for first row)
                    debit = 0.0
                    credit = amount
                # Extract description
                desc_match = re.match(r'(.*?)\s+[\d,]+\.\d{2}', rest)
                desc = desc_match.group(1).strip() if desc_match else rest.strip()
                transactions.append({
                    'date': date,
                    'time': time_str[:5],
                    'description': desc,
                    'debit': debit,
                    'credit': credit,
                    'balance': balance,
                })
    return transactions


def _parse_text_block(text: str) -> list:
    """Core TTB parsing — works on plain text (PDF or OCR output)."""
    transactions = []
    for line in text.split('\n'):
        # (cid:XXX) won't appear in OCR output but strip just in case
        line = _strip_cid(line)
        m = re.match(r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.*)', line)
        if not m:
            continue
        date_str, time_str, rest = m.groups()
        if 'ยอดคงเหลือยกมา' in rest or 'ยอดยกมา' in rest:
            continue
        amounts = re.findall(r'[\d,]+\.\d{2}', rest)
        if len(amounts) < 2:
            continue
        try:
            amount = _parse_amount(amounts[-2])
            balance = _parse_amount(amounts[-1])
        except (ValueError, IndexError):
            continue
        try:
            date = datetime.strptime(date_str, '%d.%m.%Y').strftime('%Y-%m-%d')
        except ValueError:
            continue
        if _is_debit(rest):
            debit, credit = amount, 0.0
        elif _is_credit(rest):
            debit, credit = 0.0, amount
        else:
            debit, credit = 0.0, amount
        desc_match = re.match(r'(.*?)\s+[\d,]+\.\d{2}', rest)
        desc = desc_match.group(1).strip() if desc_match else rest.strip()
        transactions.append({
            'date': date, 'time': time_str[:5], 'description': desc,
            'debit': debit, 'credit': credit, 'balance': balance,
        })
    return transactions


def parse_from_text(text: str) -> list:
    """Parse from OCR-extracted text."""
    from ocr_engine import normalize_amounts
    return _parse_text_block(normalize_amounts(text))

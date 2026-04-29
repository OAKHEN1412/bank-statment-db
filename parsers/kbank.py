import re
import pdfplumber
from datetime import datetime


CREDIT_KEYWORDS = ['รับโอน', 'รับเงิน', 'ฝากเงิน', 'ดอกเบี้ย', 'รับคืน', 'ได้รับ']
DEBIT_KEYWORDS  = ['โอนเงิน', 'ถอนเงิน', 'ค่าธรรมเนียม', 'ค่าบริการ', 'ชำระ', 'จ่าย', 'หัก']


def _is_credit(desc):
    for kw in CREDIT_KEYWORDS:
        if kw in desc:
            return True
    return False


def _parse_amount(s):
    return float(s.replace(',', ''))


def _convert_date(date_str):
    """DD-MM-YY where YY is CE year (25 -> 2025, 26 -> 2026)"""
    parts = date_str.split('-')
    if len(parts) != 3:
        return None
    day, mon, yr = parts
    year = int(yr) + 2000
    try:
        return datetime(year, int(mon), int(day)).strftime('%Y-%m-%d')
    except ValueError:
        return None


def parse(filepath):
    """
    KBANK format:
    DD-MM-YY HH:MM DESCRIPTION AMOUNT BALANCE CHANNEL DETAILS
    Amount is debit or credit determined by description keyword.
    """
    transactions = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                # Must start with DD-MM-YY HH:MM
                m = re.match(r'(\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(.*)', line)
                if not m:
                    continue
                date_str, time_str, rest = m.groups()
                # Skip opening balance line
                if 'ยอดยกมา' in rest:
                    continue
                # Find all monetary amounts (no negative in KBANK)
                amounts = re.findall(r'[\d,]+\.\d{2}', rest)
                if len(amounts) < 2:
                    continue
                try:
                    amount = _parse_amount(amounts[0])
                    balance = _parse_amount(amounts[1])
                except (ValueError, IndexError):
                    continue
                date = _convert_date(date_str)
                if not date:
                    continue
                # Get description (text before first amount)
                desc_match = re.match(r'(.*?)\s+[\d,]+\.\d{2}', rest)
                desc = desc_match.group(1).strip() if desc_match else rest.strip()
                if _is_credit(desc):
                    credit = amount
                    debit = 0.0
                else:
                    debit = amount
                    credit = 0.0
                transactions.append({
                    'date': date,
                    'time': time_str,
                    'description': desc,
                    'debit': debit,
                    'credit': credit,
                    'balance': balance,
                })
    return transactions


# ── refactored core so OCR can reuse the same logic ──────────────────────────

def _parse_text_block(text: str) -> list:
    transactions = []
    for line in text.split('\n'):
        m = re.match(r'(\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(.*)', line)
        if not m:
            continue
        date_str, time_str, rest = m.groups()
        if 'ยอดยกมา' in rest:
            continue
        amounts = re.findall(r'[\d,]+\.\d{2}', rest)
        if len(amounts) < 2:
            continue
        try:
            amount = _parse_amount(amounts[0])
            balance = _parse_amount(amounts[1])
        except (ValueError, IndexError):
            continue
        date = _convert_date(date_str)
        if not date:
            continue
        desc_match = re.match(r'(.*?)\s+[\d,]+\.\d{2}', rest)
        desc = desc_match.group(1).strip() if desc_match else rest.strip()
        if _is_credit(desc):
            credit, debit = amount, 0.0
        else:
            debit, credit = amount, 0.0
        transactions.append({
            'date': date, 'time': time_str, 'description': desc,
            'debit': debit, 'credit': credit, 'balance': balance,
        })
    return transactions


def parse_from_text(text: str) -> list:
    """Parse from OCR-extracted text."""
    from ocr_engine import normalize_amounts
    return _parse_text_block(normalize_amounts(text))

import re
import pdfplumber
from datetime import datetime


def _parse_amount(s):
    return float(s.replace(',', ''))


def parse(filepath):
    """
    KTB format:
    DATE TIME [TELLER] CODE DESCRIPTION [CHEQUE] AMOUNT TAX BALANCE [BRANCH]
    Amount is negative for debit, positive for credit.
    Tax column is always .00
    """
    transactions = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                # Must start with DD/MM/YYYY HH:MM:SS
                if not re.match(r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}', line):
                    continue
                m = re.match(
                    r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.*)',
                    line
                )
                if not m:
                    continue
                date_str, time_str, rest = m.groups()
                # Find all decimal amounts (include .00 style like tax)
                amounts = re.findall(r'-?(?:\d[\d,]*)?\.\d{2}(?!\d)', rest)
                amounts = [a for a in amounts if a not in ('', '.')]
                # Need at least 3: amount, tax (.00), balance
                if len(amounts) < 3:
                    # Sometimes tax is missing — try 2
                    if len(amounts) < 2:
                        continue
                    amount_raw = _parse_amount(amounts[0])
                    balance = _parse_amount(amounts[1])
                else:
                    amount_raw = _parse_amount(amounts[-3])
                    balance = _parse_amount(amounts[-1])
                try:
                    date = datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
                except ValueError:
                    continue
                if amount_raw < 0:
                    debit = abs(amount_raw)
                    credit = 0.0
                else:
                    credit = amount_raw
                    debit = 0.0
                # Extract description
                desc_match = re.match(r'(.*?)\s+-?(?:\d[\d,]*)?\.\d{2}', rest)
                desc = desc_match.group(1).strip() if desc_match else rest.strip()
                # Clean up teller ID and transaction codes (leading digits/codes)
                desc = re.sub(r'^\d{3,6}\s+', '', desc)
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
    transactions = []
    for line in text.split('\n'):
        if not re.match(r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}', line):
            continue
        m = re.match(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.*)', line)
        if not m:
            continue
        date_str, time_str, rest = m.groups()
        amounts = re.findall(r'-?(?:\d[\d,]*)?\.(\d{2})(?!\d)', rest)
        amounts_raw = re.findall(r'-?(?:\d[\d,]*)?\.(\d{2})(?!\d)', rest)
        amounts = re.findall(r'-?(?:\d[\d,]*)?\.[\d]{2}(?!\d)', rest)
        amounts = [a for a in amounts if a not in ('', '.')]
        if len(amounts) < 2:
            continue
        try:
            if len(amounts) >= 3:
                amount_raw = _parse_amount(amounts[-3])
                balance = _parse_amount(amounts[-1])
            else:
                amount_raw = _parse_amount(amounts[0])
                balance = _parse_amount(amounts[1])
        except (ValueError, IndexError):
            continue
        try:
            date = datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
        except ValueError:
            continue
        debit = abs(amount_raw) if amount_raw < 0 else 0.0
        credit = amount_raw if amount_raw >= 0 else 0.0
        desc_match = re.match(r'(.*?)\s+-?(?:\d[\d,]*)?\.[\d]{2}', rest)
        desc = desc_match.group(1).strip() if desc_match else rest.strip()
        desc = re.sub(r'^\d{3,6}\s+', '', desc)
        transactions.append({
            'date': date, 'time': time_str[:5], 'description': desc,
            'debit': debit, 'credit': credit, 'balance': balance,
        })
    return transactions


def parse_from_text(text: str) -> list:
    """Parse from OCR-extracted text."""
    from ocr_engine import normalize_amounts
    return _parse_text_block(normalize_amounts(text))

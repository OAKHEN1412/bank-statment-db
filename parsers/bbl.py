import re
import pdfplumber
from datetime import datetime


def _parse_amount(s):
    return float(s.replace(',', ''))


def _parse_text_block(text: str) -> list:
    """
    BBL Transaction Report format:
    DATE TIME VALUE_DATE DESCRIPTION [CHEQUENO] DEBIT CREDIT BALANCE [CHANNEL] [BRANCH]
    Debit is shown as negative (e.g. -53,600.00), Credit is positive.
    """
    transactions = []
    for line in text.split('\n'):
                # Must start with DD/MM/YYYY HH:MM:SS
                if not re.match(r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}', line):
                    continue
                m = re.match(
                    r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+\d{2}/\d{2}/\d{4}\s+(.*)',
                    line
                )
                if not m:
                    continue
                date_str, time_str, rest = m.groups()
                # Find all monetary amounts (include .00 style)
                amounts = re.findall(r'-?(?:\d[\d,]*)?\.\d{2}(?!\d)', rest)
                # Filter out empty matches and parse
                amounts = [a for a in amounts if a not in ('', '.')]
                if len(amounts) < 3:
                    continue
                try:
                    debit_raw = _parse_amount(amounts[-3])
                    credit_raw = _parse_amount(amounts[-2])
                    balance = _parse_amount(amounts[-1])
                except (ValueError, IndexError):
                    continue
                # BBL shows debit as negative value in debit column
                actual_debit = abs(debit_raw) if debit_raw < 0 else 0.0
                actual_credit = credit_raw if credit_raw > 0 else 0.0
                try:
                    date = datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
                except ValueError:
                    continue
                # Extract description (text before first amount pattern)
                desc_match = re.match(r'(.*?)\s+-?(?:\d[\d,]*)?\.\d{2}', rest)
                desc = desc_match.group(1).strip() if desc_match else rest.strip()
                # Remove long numeric cheque numbers from description
                desc = re.sub(r'\s+\d{10,}\s*', ' ', desc).strip()
                transactions.append({
                    'date': date,
                    'time': time_str[:5],
                    'description': desc,
                    'debit': actual_debit,
                    'credit': actual_credit,
                    'balance': balance,
                })
    return transactions


def parse(filepath: str) -> list:
    transactions = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                transactions.extend(_parse_text_block(text))
    return transactions


def parse_from_text(text: str) -> list:
    """Parse from OCR-extracted text (normalise amounts first)."""
    from ocr_engine import normalize_amounts
    return _parse_text_block(normalize_amounts(text))

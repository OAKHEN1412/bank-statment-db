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


def parse(filepath):
    """
    SCB format:
    DD/MM/YY HH:MM X1/X2 CHANNEL AMOUNT BALANCE DESCRIPTION
    X1 = credit (incoming), X2 = debit (outgoing)
    """
    transactions = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                # Must start with DD/MM/YY HH:MM X1 or X2
                m = re.match(
                    r'(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2})\s+(X[12])\s+(.*)',
                    line
                )
                if not m:
                    continue
                date_str, time_str, code, rest = m.groups()
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
                # Description is everything after the two amounts
                rest_after = re.sub(r'^.*?[\d,]+\.\d{2}\s+[\d,]+\.\d{2}', '', rest).strip()
                # Remove leading channel name (all-caps or Thai), keep meaningful description
                channel_match = re.match(r'^([A-Z]+)\s+(.*)', rest)
                channel = channel_match.group(1) if channel_match else ''
                # Build clean description
                desc_parts = [code]
                if channel:
                    desc_parts.append(channel)
                if rest_after:
                    desc_parts.append(rest_after)
                desc = ' '.join(desc_parts)
                if code == 'X1':
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


def _parse_text_block(text: str) -> list:
    transactions = []
    for line in text.split('\n'):
        m = re.match(r'(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2})\s+(X[12])\s+(.*)', line)
        if not m:
            continue
        date_str, time_str, code, rest = m.groups()
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
        rest_after = re.sub(r'^.*?[\d,]+\.\d{2}\s+[\d,]+\.\d{2}', '', rest).strip()
        channel_match = re.match(r'^([A-Z]+)\s+(.*)', rest)
        channel = channel_match.group(1) if channel_match else ''
        desc_parts = [code]
        if channel:
            desc_parts.append(channel)
        if rest_after:
            desc_parts.append(rest_after)
        desc = ' '.join(desc_parts)
        credit = amount if code == 'X1' else 0.0
        debit = amount if code == 'X2' else 0.0
        transactions.append({
            'date': date, 'time': time_str, 'description': desc,
            'debit': debit, 'credit': credit, 'balance': balance,
        })
    return transactions


def parse_from_text(text: str) -> list:
    """Parse from OCR-extracted text."""
    from ocr_engine import normalize_amounts
    return _parse_text_block(normalize_amounts(text))

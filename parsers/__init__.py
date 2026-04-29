from parsers import bbl, kbank, ktb, scb, ttb

PARSERS = {
    'BBL':   bbl,
    'KBANK': kbank,
    'KTB':   ktb,
    'SCB':   scb,
    'TTB':   ttb,
}


def parse_pdf(bank, filepath):
    parser = PARSERS.get(bank.upper())
    if not parser:
        raise ValueError(f'ไม่รองรับธนาคาร: {bank}')
    try:
        return parser.parse(filepath)
    except Exception as e:
        msg = str(e).lower()
        if 'password' in msg or 'incorrect' in msg or 'pdfminerexception' in type(e).__name__.lower():
            raise ValueError('ไฟล์ PDF นี้ล็อกรหัสผ่านอยู่ — กรุณาปลดล็อกก่อน import') from e
        raise ValueError(f'ไม่สามารถเปิดไฟล์ PDF ได้: {e}') from e

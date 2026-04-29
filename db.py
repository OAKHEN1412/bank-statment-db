import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'bank_statements.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bank        TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            time        TEXT,
            description TEXT,
            debit       REAL    DEFAULT 0,
            credit      REAL    DEFAULT 0,
            balance     REAL,
            source_file TEXT,
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS import_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bank        TEXT,
            filename    TEXT,
            row_count   INTEGER,
            status      TEXT,
            via_ocr     INTEGER DEFAULT 0,
            message     TEXT,
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_tx_bank_date ON transactions(bank, date);
    ''')
    # Migrate: add via_ocr column if it doesn't exist yet
    try:
        conn.execute('ALTER TABLE import_logs ADD COLUMN via_ocr INTEGER DEFAULT 0')
        conn.commit()
    except Exception:
        pass  # column already exists

    # Migrate: rebuild unique index WITHOUT source_file so same transaction
    # from monthly + merged files is stored only once.
    try:
        # Drop old index that included source_file
        conn.execute('DROP INDEX IF EXISTS idx_tx_unique')
        conn.commit()
    except Exception:
        pass

    try:
        # Remove duplicates keeping the row with the smallest id
        conn.execute('''
            DELETE FROM transactions
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM transactions
                GROUP BY bank, date, time, description, debit, credit, balance
            )
        ''')
        conn.commit()
        conn.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_unique
            ON transactions(bank, date, time, description, debit, credit, balance)
        ''')
        conn.commit()
    except Exception:
        pass  # index already exists
    conn.close()


def file_already_imported(bank, filename):
    """Return True if this filename was already imported for this bank."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM import_logs WHERE bank=? AND filename=? AND status='success' LIMIT 1",
        (bank, filename)
    ).fetchone()
    conn.close()
    return row is not None


def save_transactions(bank, rows, filename):
    conn = get_conn()
    cur = conn.cursor()
    count = 0
    skipped = 0
    for r in rows:
        try:
            cur.execute('''
                INSERT INTO transactions (bank, date, time, description, debit, credit, balance, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bank,
                r.get('date', ''),
                r.get('time', ''),
                r.get('description', ''),
                r.get('debit', 0) or 0,
                r.get('credit', 0) or 0,
                r.get('balance'),
                filename,
            ))
            count += 1
        except sqlite3.IntegrityError:
            # Duplicate row — skip silently
            skipped += 1
    cur.execute('''
        INSERT INTO import_logs (bank, filename, row_count, status, message)
        VALUES (?, ?, ?, 'success', ?)
    ''', (bank, filename, count, f'ข้ามรายการซ้ำ {skipped} รายการ' if skipped else ''))
    conn.commit()
    conn.close()
    return count, skipped


def get_transactions(bank='', date_from='', date_to='', page=1, per_page=200):
    conn = get_conn()
    where = ['1=1']
    params = []
    if bank:
        where.append('bank = ?')
        params.append(bank)
    if date_from:
        where.append('date >= ?')
        params.append(date_from)
    if date_to:
        where.append('date <= ?')
        params.append(date_to)
    where_sql = ' AND '.join(where)

    total = conn.execute(f'SELECT COUNT(*) FROM transactions WHERE {where_sql}', params).fetchone()[0]
    offset = (page - 1) * per_page
    rows = conn.execute(
        f'SELECT * FROM transactions WHERE {where_sql} ORDER BY bank, date, time LIMIT ? OFFSET ?',
        params + [per_page, offset]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_banks():
    conn = get_conn()
    rows = conn.execute('SELECT DISTINCT bank FROM transactions ORDER BY bank').fetchall()
    conn.close()
    return [r['bank'] for r in rows]


def get_summary():
    conn = get_conn()
    rows = conn.execute('''
        SELECT bank,
               COUNT(*)        AS total,
               SUM(credit)     AS total_credit,
               SUM(debit)      AS total_debit,
               MIN(date)       AS min_date,
               MAX(date)       AS max_date
        FROM transactions
        GROUP BY bank
        ORDER BY bank
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_import_logs():
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM import_logs ORDER BY created_at DESC LIMIT 50'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_bank(bank):
    conn = get_conn()
    conn.execute('DELETE FROM transactions WHERE bank = ?', (bank,))
    conn.commit()
    conn.close()


def delete_file(bank, filename):
    conn = get_conn()
    conn.execute('DELETE FROM transactions WHERE bank = ? AND source_file = ?', (bank, filename))
    conn.commit()
    conn.close()


def find_match(bank, date_str, time_hm, amount):
    """
    Try to find a matching transaction in the DB using a 4-tier strategy.
    Returns the best matching row as dict, or None.
    Tiers (best-to-worst):
      1. bank + date + time(HH:MM) + amount (credit)
      2. bank + date + amount (credit)  — any time
      3. bank + date + time(HH:MM) + amount (debit)
      4. bank + date + amount (debit)
      5. any bank + date + time(HH:MM) + amount
    """
    conn = get_conn()
    queries = [
        # (sql, params)
        ('SELECT * FROM transactions WHERE bank=? AND date=? AND time LIKE ? AND ABS(COALESCE(credit,0)-?)<0.02 ORDER BY id LIMIT 1',
         (bank, date_str, time_hm + '%', amount)),
        ('SELECT * FROM transactions WHERE bank=? AND date=? AND ABS(COALESCE(credit,0)-?)<0.02 ORDER BY id LIMIT 1',
         (bank, date_str, amount)),
        ('SELECT * FROM transactions WHERE bank=? AND date=? AND time LIKE ? AND ABS(COALESCE(debit,0)-?)<0.02 ORDER BY id LIMIT 1',
         (bank, date_str, time_hm + '%', amount)),
        ('SELECT * FROM transactions WHERE bank=? AND date=? AND ABS(COALESCE(debit,0)-?)<0.02 ORDER BY id LIMIT 1',
         (bank, date_str, amount)),
        ('SELECT * FROM transactions WHERE date=? AND time LIKE ? AND ABS(COALESCE(credit,0)-?)<0.02 ORDER BY id LIMIT 1',
         (date_str, time_hm + '%', amount)),
    ]
    result = None
    for sql, params in queries:
        row = conn.execute(sql, params).fetchone()
        if row:
            result = dict(row)
            break
    conn.close()
    return result

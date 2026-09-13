"""演示单据共享递增编号；旧编号保留为查询和办理别名。"""
import re

FIRST_NUMBER = 123000001


def next_document_number(conn):
    if not conn.in_transaction:
        raise RuntimeError('单号须在单据写事务中分配。')
    number = conn.execute('SELECT next_value FROM document_number_sequence WHERE id=1').fetchone()[0]
    conn.execute('UPDATE document_number_sequence SET next_value=? WHERE id=1', (number + 1,))
    return str(number)


def initialize_document_numbers(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS document_number_sequence(
            id INTEGER PRIMARY KEY CHECK(id=1), next_value INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS document_number_aliases(
            alias TEXT PRIMARY KEY, application_id TEXT NOT NULL);
    ''')
    conn.execute('BEGIN IMMEDIATE')
    try:
        rows = conn.execute('SELECT id,application_no FROM applications ORDER BY created_at,rowid').fetchall()
        def numbered(value):
            return bool(re.fullmatch(r'[0-9]{9}', value)) and int(value) >= FIRST_NUMBER
        existing = [int(row['application_no']) for row in rows if numbered(row['application_no'])]
        minimum = max([FIRST_NUMBER, *(value + 1 for value in existing)])
        conn.execute('INSERT OR IGNORE INTO document_number_sequence VALUES(1,?)', (minimum,))
        conn.execute('UPDATE document_number_sequence SET next_value=MAX(next_value,?) WHERE id=1', (minimum,))
        for row in rows:
            if numbered(row['application_no']): continue
            conn.execute('INSERT OR IGNORE INTO document_number_aliases VALUES(?,?)', (row['application_no'], row['id']))
            conn.execute('UPDATE applications SET application_no=? WHERE id=?', (next_document_number(conn), row['id']))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

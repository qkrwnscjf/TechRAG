import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "documents.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            url TEXT PRIMARY KEY,
            chunk_count INTEGER,
            created_at TEXT,
            content_hash TEXT
        )
    ''')
    try:
        cursor.execute('ALTER TABLE documents ADD COLUMN content_hash TEXT')
    except sqlite3.OperationalError:
        pass # Column already exists
    conn.commit()
    conn.close()

def add_document(url: str, chunk_count: int, content_hash: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    created_at = datetime.now().isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO documents (url, chunk_count, created_at, content_hash)
        VALUES (?, ?, ?, ?)
    ''', (url, chunk_count, created_at, content_hash))
    conn.commit()
    conn.close()

def get_documents():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT url, chunk_count, created_at, content_hash FROM documents ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [{"url": row[0], "chunk_count": row[1], "loaded_at": row[2], "content_hash": row[3]} for row in rows]

def get_document(url: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT url, chunk_count, created_at, content_hash FROM documents WHERE url = ?', (url,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"url": row[0], "chunk_count": row[1], "loaded_at": row[2], "content_hash": row[3]}
    return None

def delete_document(url: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM documents WHERE url = ?', (url,))
    conn.commit()
    conn.close()

# Initialize on import
init_db()

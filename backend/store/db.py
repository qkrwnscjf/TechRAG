import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "documents.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            url TEXT PRIMARY KEY,
            chunk_count INTEGER,
            created_at TEXT,
            content_hash TEXT
        )
    ''')
    # 기존 DB 에 컬럼을 덧붙이는 마이그레이션. 이미 있으면 OperationalError 가 나므로 넘긴다.
    #
    # include_ext / exclude_paths 를 문서마다 저장하는 이유:
    # 수집 필터는 레포마다 달라야 한다(vLLM 은 rust·fixtures, Prefect 는 api-ref·plans 를 버린다).
    # 그런데 설정은 전역 하나뿐이라, 다른 레포를 넣으려고 설정을 바꾸면
    # 야간 스케줄러가 기존 문서를 "바뀐 필터" 로 재수집해 색인을 망가뜨린다.
    # 수집 당시 쓴 필터를 함께 기록해 두고, 재수집할 때 그 필터를 다시 쓴다.
    for col in ("content_hash TEXT", "include_ext TEXT", "exclude_paths TEXT"):
        try:
            cursor.execute(f'ALTER TABLE documents ADD COLUMN {col}')
        except sqlite3.OperationalError:
            pass  # 이미 존재하는 컬럼
    conn.commit()
    conn.close()

def add_document(url: str, chunk_count: int, content_hash: str = None,
                 include_ext: str = None, exclude_paths: str = None):
    """수집 결과를 기록한다. include_ext / exclude_paths 는 이 문서를 수집할 때 쓴 필터다."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()
    created_at = datetime.now().isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO documents
            (url, chunk_count, created_at, content_hash, include_ext, exclude_paths)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (url, chunk_count, created_at, content_hash, include_ext, exclude_paths))
    conn.commit()
    conn.close()

def get_documents():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()
    cursor.execute('SELECT url, chunk_count, created_at, content_hash, include_ext, exclude_paths FROM documents ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [{"url": row[0], "chunk_count": row[1], "loaded_at": row[2], "content_hash": row[3], "include_ext": row[4], "exclude_paths": row[5]} for row in rows]

def get_document(url: str):
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()
    cursor.execute('SELECT url, chunk_count, created_at, content_hash, include_ext, exclude_paths FROM documents WHERE url = ?', (url,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"url": row[0], "chunk_count": row[1], "loaded_at": row[2], "content_hash": row[3], "include_ext": row[4], "exclude_paths": row[5]}
    return None

def delete_document(url: str):
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM documents WHERE url = ?', (url,))
    conn.commit()
    conn.close()

# Initialize on import
init_db()

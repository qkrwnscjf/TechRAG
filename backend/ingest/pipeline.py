import hashlib
from typing import Tuple
from ingest.loader import load_from_url
from ingest.chunker import chunk_documents
from store.vectorstore import vector_store_manager
import store.db as db

def generate_hash(text: str) -> str:
    """Generate SHA-256 hash for the given text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def process_url(url: str, force: bool = False) -> Tuple[str, str, int]:
    """
    Process a single URL: load, hash-check, chunk, and update vector store.
    Returns (status, message, chunks_added)
    status can be: 'ok', 'skipped', 'error'
    """
    try:
        # 1. Load documents
        docs = load_from_url(url)
        if not docs:
            return 'error', 'No documents loaded.', 0
            
        # 2. Generate Content Hash
        full_text = "\n".join([doc.page_content for doc in docs])
        current_hash = generate_hash(full_text)
        
        # 3. Check existing hash (Smart Update)
        existing_doc = db.get_document(url)
        if not force and existing_doc and existing_doc.get('content_hash') == current_hash:
            return 'skipped', 'Document content has not changed. Skipped update.', 0
            
        # 4. Chunking
        chunks = chunk_documents(docs)
        if not chunks:
            return 'error', 'Failed to chunk documents.', 0
            
        # 5. Vector Store Update (해당 source 의 기존 벡터를 지우고 새로 적재)
        #    add_documents 는 배치별로 넣고 "실제 적재된 수" 를 돌려준다.
        added = vector_store_manager.add_documents(chunks)

        if added == 0:
            return 'error', 'No chunks were stored. See logs for the upsert failure.', 0

        # 6. Update SQLite Tracker
        if added < len(chunks):
            # 일부 배치가 실패했다. 여기서 해시를 기록하면 다음 수집이 "변경 없음" 으로
            # 건너뛰어 불완전한 색인이 영구히 남는다. 해시를 남기지 않아 다시 시도하게 한다.
            db.add_document(url, added, None)
            return ('partial',
                    f'Stored {added}/{len(chunks)} chunks. Hash not recorded so the next run retries.',
                    added)

        db.add_document(url, added, current_hash)
        return 'ok', f'Successfully updated. Added {added} chunks.', added
    except Exception as e:
        return 'error', str(e), 0

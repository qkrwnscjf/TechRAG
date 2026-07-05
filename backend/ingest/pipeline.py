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
            
        # 5. Vector Store Update (Automatically deletes old chunks for this source)
        vector_store_manager.add_documents(chunks)
        
        # 6. Update SQLite Tracker
        db.add_document(url, len(chunks), current_hash)
        
        return 'ok', f'Successfully updated. Added {len(chunks)} chunks.', len(chunks)
    except Exception as e:
        return 'error', str(e), 0

import hashlib
import logging
from typing import Tuple, Optional
from ingest.loader import load_from_url
from config import get_include_exts, get_md_excludes
from ingest.chunker import chunk_documents
from store.vectorstore import get_vector_store_manager
import store.db as db

logger = logging.getLogger(__name__)


def _csv(items) -> str:
    """필터 목록을 DB 에 저장할 문자열로."""
    return ",".join(items)


def _split(text: Optional[str]):
    """DB 에 저장된 문자열을 필터 목록으로. 값이 없으면 None(=전역 설정 사용)."""
    if not text:
        return None
    return [x.strip() for x in text.split(",") if x.strip()]

def generate_hash(text: str) -> str:
    """Generate SHA-256 hash for the given text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def process_url(url: str, force: bool = False,
                include_ext: str = None, exclude_paths: str = None) -> Tuple[str, str, int]:
    """
    URL 하나를 수집한다: 로드 -> 해시 검사 -> 청킹 -> 벡터 적재.
    반환: (status, message, chunks_added).  status: 'ok' | 'partial' | 'skipped' | 'error'

    수집 필터(include_ext / exclude_paths)는 다음 순서로 정해진다.

      1) 호출 인자로 명시된 값        — 새 레포를 넣을 때 요청에 실어 보낸다
      2) 이 문서가 이전에 쓴 값        — 재수집(스케줄러 포함)은 반드시 원래 필터를 다시 쓴다
      3) 전역 설정(.env)              — 위 둘이 없을 때의 기본값

    2번이 핵심이다. 필터는 레포마다 달라야 하는데 전역 설정은 하나뿐이라,
    다른 레포를 넣으려고 설정을 바꾸면 야간 스케줄러가 기존 문서를 바뀐 필터로
    재수집해 색인을 조용히 망가뜨린다. 수집 당시 필터를 문서와 함께 저장해 그것을 막는다.
    """
    try:
        existing_doc = db.get_document(url)

        if include_ext or exclude_paths:
            eff_ext, eff_exc = include_ext, exclude_paths
        elif existing_doc and existing_doc.get("include_ext"):
            eff_ext = existing_doc.get("include_ext")
            eff_exc = existing_doc.get("exclude_paths")
            logger.info("Reusing stored filter for %s (ext=%s)", url, eff_ext)
        else:
            eff_ext, eff_exc = _csv(get_include_exts()), _csv(get_md_excludes())

        # 1. Load documents
        docs = load_from_url(url, include_exts=_split(eff_ext), excludes=_split(eff_exc))
        if not docs:
            return 'error', 'No documents loaded.', 0
            
        # 2. Generate Content Hash
        full_text = "\n".join([doc.page_content for doc in docs])
        current_hash = generate_hash(full_text)
        
        # 3. Check existing hash (Smart Update)
        if not force and existing_doc and existing_doc.get('content_hash') == current_hash:
            return 'skipped', 'Document content has not changed. Skipped update.', 0
            
        # 4. Chunking
        chunks = chunk_documents(docs)
        if not chunks:
            return 'error', 'Failed to chunk documents.', 0
            
        # 5. Vector Store Update (해당 source 의 기존 벡터를 지우고 새로 적재)
        #    add_documents 는 배치별로 넣고 "실제 적재된 수" 를 돌려준다.
        added = get_vector_store_manager().add_documents(chunks)

        if added == 0:
            return 'error', 'No chunks were stored. See logs for the upsert failure.', 0

        # 6. Update SQLite Tracker
        if added < len(chunks):
            # 일부 배치가 실패했다. 여기서 해시를 기록하면 다음 수집이 "변경 없음" 으로
            # 건너뛰어 불완전한 색인이 영구히 남는다. 해시를 남기지 않아 다시 시도하게 한다.
            db.add_document(url, added, None, eff_ext, eff_exc)
            return ('partial',
                    f'Stored {added}/{len(chunks)} chunks. Hash not recorded so the next run retries.',
                    added)

        db.add_document(url, added, current_hash, eff_ext, eff_exc)
        return 'ok', f'Successfully updated. Added {added} chunks.', added
    except Exception as e:
        return 'error', str(e), 0

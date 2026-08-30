import logging
import threading
from typing import List, Dict, Any

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from config import settings, resolve_device

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024        # BAAI/bge-m3
UPSERT_BATCH = 64           # 한 번에 임베딩·적재할 청크 수
DELETE_BATCH = 1000         # Pinecone 요청당 삭제 ID 상한


class VectorStoreManager:
    def __init__(self):
        device = resolve_device()
        logger.info("Embedding device: %s", device)

        # normalize_embeddings=True 가 중요하다.
        # 인덱스 메트릭이 dotproduct 인데 정규화하지 않으면 벡터 크기가 유사도에 섞인다.
        # 정규화하면 dotproduct == cosine 이 되어 인덱스를 다시 만들지 않고도 정확히 동작한다.
        # (bge-m3 는 원래 정규화해서 쓰는 것이 표준이다.)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-m3",
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True},
        )

        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index_name

        existing = self.pc.list_indexes().names()
        if self.index_name in existing:
            info = self.pc.describe_index(self.index_name)
            if getattr(info, "metric", "") not in ("dotproduct", "cosine"):
                raise RuntimeError(
                    f"Pinecone 인덱스 '{self.index_name}' 의 메트릭이 "
                    f"'{info.metric}' 입니다. dotproduct 또는 cosine 이어야 합니다."
                )
        else:
            logger.info("Creating Pinecone index '%s' (dim=%d)", self.index_name, EMBEDDING_DIM)
            self.pc.create_index(
                name=self.index_name,
                dimension=EMBEDDING_DIM,
                metric="dotproduct",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )

        self.index = self.pc.Index(self.index_name)
        self.store = PineconeVectorStore(index=self.index, embedding=self.embeddings, text_key="text")

    # ------------------------------------------------------------------ #
    # 쓰기
    # ------------------------------------------------------------------ #
    def add_documents(self, chunks: List[Document]) -> int:
        """
        source URL 단위로 기존 벡터를 지우고 새로 적재한다. 적재된 청크 수를 반환.

        배치 단위로 나눠 넣는 이유:
        이전 구현은 전체를 한 번의 add_texts 로 넘기고 실패하면 tenacity 가 처음부터
        재시도했다. 수천 청크짜리 수집에서 중간에 한 번 실패하면 앞서 끝낸 작업을 통째로
        버리고 다시 시작했고, 예외를 기록하지 않아 무엇이 실패했는지도 알 수 없었다.
        (실제로 30분 넘게 같은 구간을 세 번 반복하고 원인을 남기지 않은 적이 있다.)

        이제는 배치마다 독립적으로 넣고, 실패한 배치만 재시도하며, 실패 원인을 로그로 남긴다.
        중간에 멈춰도 "어디까지 들어갔는지"가 반환값으로 드러난다.
        """
        if not chunks:
            return 0

        for source in {c.metadata.get("source") for c in chunks if "source" in c.metadata}:
            removed = self.delete_source(source)
            logger.info("Replaced source %s (removed %d old vectors)", source, removed)

        # chunk_index 는 chunker 가 배치 전체에서 유일하게 매긴 값이다.
        ids = [f"{c.metadata.get('source', 'unknown')}_{c.metadata['chunk_index']}" for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"벡터 ID가 {len(ids) - len(set(ids))}개 중복되었습니다. "
                f"chunker 의 chunk_index 유일성을 확인하세요."
            )

        texts = [c.page_content for c in chunks]
        metadatas = [c.metadata for c in chunks]

        total = len(chunks)
        added = 0
        failed_batches = 0

        for start in range(0, total, UPSERT_BATCH):
            end = min(start + UPSERT_BATCH, total)
            for attempt in (1, 2, 3):
                try:
                    self.store.add_texts(
                        texts=texts[start:end],
                        metadatas=metadatas[start:end],
                        ids=ids[start:end],
                    )
                    added += end - start
                    break
                except Exception as e:
                    logger.warning(
                        "Upsert 실패 (청크 %d-%d, 시도 %d/3): %s: %s",
                        start, end - 1, attempt, type(e).__name__, str(e)[:300],
                    )
                    if attempt == 3:
                        failed_batches += 1
                        logger.error("청크 %d-%d 를 건너뜁니다.", start, end - 1)

            logger.info("적재 진행 %d/%d (%.0f%%)", end, total, 100 * end / total)

        if failed_batches:
            logger.error("총 %d개 배치가 실패했습니다. 적재된 청크: %d/%d",
                         failed_batches, added, total)
        return added

    # ------------------------------------------------------------------ #
    # 읽기
    # ------------------------------------------------------------------ #
    def as_retriever(self, k: int = 4):
        return self.store.as_retriever(search_kwargs={"k": k})

    def get_doc_list(self) -> List[Dict[str, Any]]:
        stats = self.index.describe_index_stats()
        return [{"url": "Pinecone Index", "chunk_count": stats.total_vector_count, "loaded_at": "N/A"}]

    # ------------------------------------------------------------------ #
    # 삭제
    # ------------------------------------------------------------------ #
    def delete_source(self, url: str) -> int:
        """
        해당 source URL 의 벡터를 모두 삭제하고 삭제된 개수를 반환.

        Pinecone Serverless 는 메타데이터 필터 삭제를 지원하지 않는다.
        ID prefix 로 대상을 나열해 ID 기반으로 지운다. (ID 규칙: f"{source}_{chunk_index}")
        """
        try:
            ids: List[str] = []
            for page in self.index.list(prefix=f"{url}_"):
                ids.extend(page)

            deleted = 0
            for i in range(0, len(ids), DELETE_BATCH):
                batch = ids[i:i + DELETE_BATCH]
                self.index.delete(ids=batch)
                deleted += len(batch)
            return deleted
        except Exception as e:
            logger.error("Pinecone 에서 %s 를 삭제하지 못했습니다: %s", url, e)
            return 0


_instance: "VectorStoreManager | None" = None
_lock = threading.Lock()


def get_vector_store_manager() -> VectorStoreManager:
    """
    싱글턴을 처음 필요할 때 만든다.

    예전에는 모듈 최하단에서 바로 생성했는데, 그러면 `store.vectorstore` 를 import 하는
    것만으로 임베딩 모델(약 2.3GB)이 메모리에 올라가고 Pinecone 접속까지 일어났다.
    이 모듈을 import 하는 어떤 코드도 테스트할 수 없었고, 모델이 필요 없는 경로까지
    로딩 비용을 물었다.

    API 서버는 어차피 모델이 필요하므로 기동 시 워밍업한다(api/main.py 의 lifespan).
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:      # 락 대기 중 다른 스레드가 만들었을 수 있다
                _instance = VectorStoreManager()
    return _instance

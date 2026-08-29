import os
import logging
from typing import List, Dict, Any
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.retrievers import PineconeHybridSearchRetriever
from pinecone import Pinecone, ServerlessSpec
from pinecone_text.sparse import BM25Encoder
from tenacity import retry, stop_after_attempt, wait_exponential
from config import settings, resolve_device

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024  # BAAI/bge-m3


class VectorStoreManager:
    def __init__(self):
        # Initialize embeddings (Dense Vector)
        device = resolve_device()
        logger.info("Embedding device: %s", device)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-m3",
            model_kwargs={"device": device}
        )

        # Initialize BM25 Encoder (Sparse Vector)
        self.bm25_encoder = BM25Encoder().default()

        # Initialize Pinecone
        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index_name

        # Ensure index is 'dotproduct' for Hybrid Search
        existing_indexes = self.pc.list_indexes().names()
        if self.index_name in existing_indexes:
            idx_info = self.pc.describe_index(self.index_name)
            if getattr(idx_info, "metric", "") == "cosine":
                # 하이브리드 검색은 dotproduct 메트릭을 요구한다.
                # 인덱스를 지우는 것은 되돌릴 수 없는 파괴적 작업이므로 기본적으로 거부하고,
                # 사용자가 명시적으로 허용했을 때만 재생성한다.
                if not settings.pinecone_allow_index_recreate:
                    raise RuntimeError(
                        f"Pinecone 인덱스 '{self.index_name}' 의 메트릭이 'cosine' 이라 "
                        f"하이브리드 검색을 쓸 수 없습니다.\n"
                        f"이 인덱스를 삭제하고 dotproduct 로 다시 만들려면 "
                        f"환경변수 PINECONE_ALLOW_INDEX_RECREATE=true 를 설정하세요. "
                        f"(기존 벡터는 모두 사라지며 문서를 재수집해야 합니다.)"
                    )
                logger.warning(
                    "Deleting existing cosine index '%s' to upgrade to Hybrid Search (dotproduct). "
                    "All existing vectors will be lost.", self.index_name
                )
                self.pc.delete_index(self.index_name)
                existing_indexes = self.pc.list_indexes().names()

        if self.index_name not in existing_indexes:
            logger.info("Creating Pinecone index '%s' (dim=%d, dotproduct)", self.index_name, EMBEDDING_DIM)
            self.pc.create_index(
                name=self.index_name,
                dimension=EMBEDDING_DIM,
                metric="dotproduct",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )

        self.index = self.pc.Index(self.index_name)

        # Setup Hybrid Retriever
        self.hybrid_retriever = PineconeHybridSearchRetriever(
            embeddings=self.embeddings,
            sparse_encoder=self.bm25_encoder,
            index=self.index,
            text_key="text",
            top_k=4,
            alpha=0.5,  # 0.5: Dense와 Sparse를 5:5 비율로 결합
        )

    # ------------------------------------------------------------------ #
    # 쓰기
    # ------------------------------------------------------------------ #
    def add_documents(self, chunks: List[Document]):
        """source URL 단위로 기존 벡터를 지우고 새로 upsert (실패 시 최대 3회 재시도)"""
        if not chunks:
            return

        sources = set(c.metadata.get("source") for c in chunks if "source" in c.metadata)
        for source in sources:
            removed = self.delete_source(source)
            logger.info("Replaced source %s (removed %d old vectors)", source, removed)

        # chunk_index 는 chunker 가 배치 전체에서 유일하게 매긴 값이다.
        # 이 값이 문서마다 리셋되면 ID가 충돌해 청크가 서로를 덮어쓴다.
        ids = [f"{c.metadata.get('source', 'unknown')}_{c.metadata['chunk_index']}" for c in chunks]
        if len(set(ids)) != len(ids):
            logger.error(
                "벡터 ID가 %d개 중복되었습니다. chunker 의 chunk_index 유일성을 확인하세요.",
                len(ids) - len(set(ids)),
            )

        texts = [c.page_content for c in chunks]
        metadatas = [c.metadata for c in chunks]

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
        def _upsert():
            self.hybrid_retriever.add_texts(texts=texts, metadatas=metadatas, ids=ids)

        _upsert()

    # ------------------------------------------------------------------ #
    # 읽기
    # ------------------------------------------------------------------ #
    def as_retriever(self, k: int = 4):
        """LangChain retriever 반환 (동적 K 적용)"""
        self.hybrid_retriever.top_k = k
        return self.hybrid_retriever

    def get_doc_list(self) -> List[Dict[str, Any]]:
        stats = self.index.describe_index_stats()
        return [{"url": "Pinecone Index", "chunk_count": stats.total_vector_count, "loaded_at": "N/A"}]

    # ------------------------------------------------------------------ #
    # 삭제
    # ------------------------------------------------------------------ #
    def delete_source(self, url: str) -> int:
        """
        해당 source URL 의 벡터를 모두 삭제하고 삭제된 개수를 반환.

        Pinecone Serverless 인덱스는 메타데이터 필터 삭제(delete(filter=...))를
        지원하지 않는다. 예전 구현은 그 호출이 던진 예외를 삼켜서 아무것도 지우지 못한 채
        성공을 반환했고, 재수집할 때마다 낡은 벡터가 계속 쌓였다.
        대신 ID prefix 로 대상을 나열해 ID 기반으로 삭제한다.
        (ID 규칙: f"{source}_{chunk_index}")
        """
        prefix = f"{url}_"
        try:
            ids: List[str] = []
            for page in self.index.list(prefix=prefix):
                ids.extend(page)

            deleted = 0
            for i in range(0, len(ids), 1000):  # Pinecone 은 요청당 1000개 제한
                batch = ids[i:i + 1000]
                self.index.delete(ids=batch)
                deleted += len(batch)
            return deleted

        except Exception as e:
            # pod 기반 구형 인덱스라면 메타데이터 필터 삭제가 동작한다. 폴백.
            logger.warning("Prefix 기반 삭제 실패(%s). 메타데이터 필터 삭제로 폴백합니다.", e)
            try:
                self.index.delete(filter={"source": {"$eq": url}})
                return 0
            except Exception as e2:
                logger.error("Pinecone 에서 %s 를 삭제하지 못했습니다: %s", url, e2)
                return 0


# Singleton instance
vector_store_manager = VectorStoreManager()

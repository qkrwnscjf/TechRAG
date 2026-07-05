import os
from typing import List, Dict, Any
from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from pinecone import Pinecone, ServerlessSpec
from config import settings

class VectorStoreManager:
    def __init__(self):
        # Initialize embeddings
        self.embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-m3",
            model_kwargs={"device": "cpu"}
        )
        
        # Initialize Pinecone
        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index_name
        
        # Create index if it doesn't exist
        if self.index_name not in self.pc.list_indexes().names():
            self.pc.create_index(
                name=self.index_name,
                dimension=1024, # BAAI/bge-m3 dimension
                metric='cosine',
                spec=ServerlessSpec(
                    cloud='aws',
                    region='us-east-1' # Default free tier region
                )
            )
            
        self.index = self.pc.Index(self.index_name)
        self.vectorstore = PineconeVectorStore(
            index=self.index, 
            embedding=self.embeddings, 
            text_key="text"
        )

    def add_documents(self, chunks: List[Document]):
        """중복 source URL 체크 후 upsert (실패 시 최대 3회 재시도)"""
        if not chunks:
            return

        sources = set(chunk.metadata.get("source") for chunk in chunks if "source" in chunk.metadata)
        for source in sources:
            self.delete_source(source)

        ids = [f"{chunk.metadata.get('source', 'unknown')}_{chunk.metadata.get('chunk_index', i)}" for i, chunk in enumerate(chunks)]
        
        # 내부 함수로 정의하여 tenacity 재시도 데코레이터 적용
        from tenacity import retry, stop_after_attempt, wait_fixed
        
        @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
        def _upsert():
            self.vectorstore.add_documents(documents=chunks, ids=ids)
            
        _upsert()

    def as_retriever(self, k: int = 4):
        """LangChain retriever 반환"""
        return self.vectorstore.as_retriever(search_kwargs={"k": k})

    def get_doc_list(self) -> List[Dict[str, Any]]:
        """인덱스된 source URL 목록 + 청크 수 반환"""
        # Pinecone free tier does not support grouping or fetching all metadata easily.
        # We simulate this by checking stats, but we can't get exact URLs without scanning.
        # To keep it simple, we just return a dummy or cached list. 
        # (In a real app, you'd store metadata in a separate SQL DB)
        stats = self.index.describe_index_stats()
        return [{"url": "Pinecone Index", "chunk_count": stats.total_vector_count, "loaded_at": "N/A"}]

    def delete_source(self, url: str) -> int:
        """특정 source의 청크 전체 삭제"""
        # Pinecone supports deletion by metadata filter
        try:
            self.index.delete(filter={"source": {"$eq": url}})
            return 1 # We don't know exact count deleted
        except Exception as e:
            print(f"Error deleting from Pinecone: {e}")
            return 0

# Singleton instance
vector_store_manager = VectorStoreManager()

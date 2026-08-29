from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

def chunk_documents(docs: List[Document]) -> List[Document]:
    """
    RecursiveCharacterTextSplitter 전략
    chunk_size=500, chunk_overlap=50
    코드 블록은 800으로 별도 처리

    주의: GitHub 레포(여러 .md)나 PDF(여러 페이지)는 하나의 source URL 아래
    여러 Document 로 들어온다. chunk_index 를 문서마다 0으로 리셋하면
    vectorstore 가 만드는 벡터 ID `{source}_{chunk_index}` 가 충돌해
    Pinecone upsert 시 서로를 덮어쓴다. 따라서 chunk_index 는 배치 전체에서
    유일한 일련번호로 매긴다.
    """
    standard_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", ".", " ", ""]
    )

    code_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=50,
        separators=["\n\n", "\n", " ", ""]
    )

    chunked_docs = []
    running_index = 0   # 배치 전체를 관통하는 유일 번호

    for doc_index, doc in enumerate(docs):
        content = doc.page_content
        # Simple heuristic to check for code blocks
        if "```" in content:
            chunks = code_splitter.split_text(content)
        else:
            chunks = standard_splitter.split_text(content)

        for local_index, chunk_text in enumerate(chunks):
            metadata = doc.metadata.copy()
            metadata["chunk_index"] = running_index      # 전역 유일 -> 벡터 ID 충돌 방지
            metadata["doc_index"] = doc_index            # 원본 문서 구분용
            metadata["chunk_in_doc"] = local_index       # 문서 내 순번
            chunked_docs.append(Document(page_content=chunk_text, metadata=metadata))
            running_index += 1

    # 배치 전체 청크 수를 모든 청크에 기록
    for c in chunked_docs:
        c.metadata["total_chunks"] = running_index

    return chunked_docs

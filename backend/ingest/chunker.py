from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

def chunk_documents(docs: List[Document]) -> List[Document]:
    """
    RecursiveCharacterTextSplitter 전략
    chunk_size=500, chunk_overlap=50
    코드 블록은 800으로 별도 처리
    """
    standard_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\\n\\n", "\\n", ".", " ", ""]
    )
    
    code_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=50,
        separators=["\\n\\n", "\\n", " ", ""]
    )
    
    chunked_docs = []
    
    for doc in docs:
        content = doc.page_content
        # Simple heuristic to check for code blocks
        if "```" in content:
            chunks = code_splitter.split_text(content)
        else:
            chunks = standard_splitter.split_text(content)
            
        total_chunks = len(chunks)
        for i, chunk_text in enumerate(chunks):
            metadata = doc.metadata.copy()
            metadata["chunk_index"] = i
            metadata["total_chunks"] = total_chunks
            
            chunked_docs.append(Document(page_content=chunk_text, metadata=metadata))
            
    return chunked_docs

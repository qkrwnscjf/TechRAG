from typing import List
from langchain_core.documents import Document
from duckduckgo_search import DDGS

def search_web(query: str, max_results: int = 5) -> List[Document]:
    """
    DuckDuckGo 검색 후 결과를 Document 리스트로 반환
    """
    docs = []
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            for res in results:
                doc = Document(
                    page_content=res.get("body", ""),
                    metadata={
                        "title": res.get("title", ""),
                        "source": res.get("href", "")
                    }
                )
                docs.append(doc)
    except Exception as e:
        print(f"Web search error: {e}")
        
    return docs

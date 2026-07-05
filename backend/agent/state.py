from typing import TypedDict, List, Dict, Any
from langchain_core.documents import Document

class AgentState(TypedDict):
    question: str
    route: str                    # "vectorstore" | "web_search"
    documents: List[Document]
    generation: str
    rewrite_count: int            # 최대 2회 재작성 제한
    trace: List[Dict[str, Any]]   # 노드 실행 로그 (SSE 전송용)

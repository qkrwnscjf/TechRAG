import operator
from typing import TypedDict, List, Dict, Any, Annotated
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    question: str
    documents: List[Document]
    generation: str
    rewrite_count: int            # 최대 2회 재작성 제한
    trace: List[Dict[str, Any]]   # 노드 실행 로그 (SSE 전송용)

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite
import asyncio
import os

from agent.state import AgentState
from agent.nodes import (
    contextualize_node,
    retriever_node,
    grader_node,
    generator_node,
    question_rewriter_node
)

def decide_to_generate(state: AgentState):
    """
    Grader 평가 후: 
    - 관련 문서가 있으면 generate
    - 없으면 rewrite (단, 2회 이상이면 generate로 넘어가서 모른다고 답변)
    """
    filtered_docs = state.get("documents", [])
    rewrite_count = state.get("rewrite_count", 0)
    
    if not filtered_docs:
        if rewrite_count < 2:
            return "rewrite"
        else:
            return "generate"
    return "generate"

workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("contextualize", contextualize_node)
workflow.add_node("retriever", retriever_node)
workflow.add_node("grader", grader_node)
workflow.add_node("generator", generator_node)
workflow.add_node("question_rewriter", question_rewriter_node)

# Build graph
workflow.set_entry_point("contextualize")

workflow.add_edge("contextualize", "retriever")
workflow.add_edge("retriever", "grader")

workflow.add_conditional_edges(
    "grader",
    decide_to_generate,
    {
        "rewrite": "question_rewriter",
        "generate": "generator"
    }
)

workflow.add_edge("question_rewriter", "retriever")
workflow.add_edge("generator", END)

# Setup Checkpointer (Memory)
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "checkpoints.sqlite")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 동기 SqliteSaver 는 graph.astream() 같은 비동기 실행을 거부한다
# (NotImplementedError: The SqliteSaver does not support async methods).
# API 서버는 SSE 로 응답을 흘리므로 그래프를 비동기로 돌려야 하고,
# 따라서 체크포인터도 비동기 구현이어야 한다.
#
# AsyncSqliteSaver 는 aiosqlite 연결을 요구하는데 그 연결은 실행 중인 이벤트 루프
# 안에서만 만들 수 있다. 모듈 import 시점에는 루프가 없으므로 첫 요청 때 한 번만
# 만들고 재사용한다.
_graph = None
_graph_lock = asyncio.Lock()


async def get_graph():
    """컴파일된 그래프를 반환한다. 최초 호출 때만 체크포인터를 만든다."""
    global _graph
    if _graph is None:
        async with _graph_lock:
            if _graph is None:                      # 락 대기 중 다른 요청이 만들었을 수 있다
                conn = await aiosqlite.connect(DB_PATH)
                _graph = workflow.compile(checkpointer=AsyncSqliteSaver(conn))
    return _graph

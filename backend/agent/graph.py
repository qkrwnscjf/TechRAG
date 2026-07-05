from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.nodes import (
    router_node,
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
workflow.add_node("router", router_node)
workflow.add_node("retriever", retriever_node)
workflow.add_node("grader", grader_node)
workflow.add_node("generator", generator_node)
workflow.add_node("question_rewriter", question_rewriter_node)

# Build graph
workflow.set_entry_point("router")

workflow.add_edge("router", "retriever")
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

# Compile
graph = workflow.compile()

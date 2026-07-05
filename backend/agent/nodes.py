import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.documents import Document
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser

from agent.state import AgentState
from agent.prompts import router_prompt, grader_prompt, generator_prompt, rewriter_prompt
from store.vectorstore import vector_store_manager
from tools.web_search import search_web
from config import settings

# Initialize LLM with Gemini 2.5 Flash
llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-2.5-flash", google_api_key=settings.google_api_key, max_retries=3)
json_llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-2.5-flash", google_api_key=settings.google_api_key, max_retries=3)

def router_node(state: AgentState) -> AgentState:
    question = state["question"]
    router_chain = router_prompt | json_llm | JsonOutputParser()
    try:
        result = router_chain.invoke({"question": question})
        route = result.get("route", "vectorstore")
        if route not in ["vectorstore", "web_search"]:
            route = "vectorstore"
    except Exception:
        route = "vectorstore"
        
    state["route"] = route
    if "trace" not in state or state["trace"] is None:
        state["trace"] = []
    state["trace"].append({"node": "router", "decision": route})
    return state

def retriever_node(state: AgentState) -> AgentState:
    question = state["question"]
    route = state.get("route", "vectorstore")
    
    docs = []
    if route == "vectorstore":
        retriever = vector_store_manager.as_retriever(k=4)
        docs = retriever.invoke(question)
    else:
        docs = search_web(question, max_results=5)
        
    state["documents"] = docs
    if "trace" not in state or state["trace"] is None:
        state["trace"] = []
    state["trace"].append({"node": "retriever", "doc_count": len(docs)})
    return state

def grader_node(state: AgentState) -> AgentState:
    question = state["question"]
    docs = state.get("documents", [])
    
    grader_chain = grader_prompt | json_llm | JsonOutputParser()
    kept_docs = []
    
    for doc in docs:
        try:
            result = grader_chain.invoke({"question": question, "document": doc.page_content})
            score = result.get("score", "no")
            if score == "yes":
                kept_docs.append(doc)
        except Exception:
            kept_docs.append(doc)
            
    kept_count = len(kept_docs)
    dropped_count = len(docs) - kept_count
    
    state["documents"] = kept_docs
    if "trace" not in state or state["trace"] is None:
        state["trace"] = []
    state["trace"].append({"node": "grader", "kept": kept_count, "dropped": dropped_count})
    return state

def generator_node(state: AgentState) -> AgentState:
    question = state["question"]
    docs = state.get("documents", [])
    
    context = "\\n\\n".join([doc.page_content for doc in docs])
    
    generator_chain = generator_prompt | llm | StrOutputParser()
    generation = generator_chain.invoke({"context": context, "question": question})
    
    sources = []
    for doc in docs:
        src = doc.metadata.get("source", "unknown")
        if src not in sources:
            sources.append(src)
            
    state["generation"] = generation
    if "trace" not in state or state["trace"] is None:
        state["trace"] = []
    state["trace"].append({"node": "generator", "sources": sources})
    return state

def question_rewriter_node(state: AgentState) -> AgentState:
    question = state["question"]
    rewriter_chain = rewriter_prompt | llm | StrOutputParser()
    
    better_question = rewriter_chain.invoke({"question": question})
    
    state["question"] = better_question
    state["rewrite_count"] = state.get("rewrite_count", 0) + 1
    if "trace" not in state or state["trace"] is None:
        state["trace"] = []
    state["trace"].append({"node": "question_rewriter", "original": question, "new": better_question})
    return state

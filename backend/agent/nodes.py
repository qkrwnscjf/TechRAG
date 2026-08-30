import json
import asyncio
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.documents import Document
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState
from agent.prompts import (router_prompt, grader_prompt, batch_grader_prompt,
                           generator_prompt, rewriter_prompt, contextualize_prompt)
from store.vectorstore import get_vector_store_manager
from tools.web_search import search_web
from agent import reranker
from config import settings

logger = logging.getLogger(__name__)

# Initialize LLM with Gemini 2.5 Flash
llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-2.5-flash", google_api_key=settings.google_api_key, max_retries=3)
json_llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-2.5-flash", google_api_key=settings.google_api_key, max_retries=3)

def contextualize_node(state: AgentState) -> dict:
    question = state["question"]
    messages = state.get("messages", [])
    
    if len(messages) > 1:
        # 마지막 항목은 방금 들어온 질문이므로 제외하고, 그 앞에서 최근 N개만 쓴다.
        history = messages[:-1][-settings.history_window:]
        chat_history = "\n".join(
            f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content}" for m in history
        )
        chain = contextualize_prompt | llm | StrOutputParser()
        standalone_question = chain.invoke({"chat_history": chat_history, "question": question})
    else:
        standalone_question = question

    new_trace = state.get("trace", []) + [{"node": "contextualize", "standalone": standalone_question}]
    return {"question": standalone_question, "trace": new_trace}

# 최신성을 묻는 신호. 이런 질문만 웹 검색으로 보내고 나머지는 문서 검색이 기본이다.
_WEB_SIGNALS = (
    "최신", "최근", "요즘", "지금까지", "언제 나왔", "언제 출시",
    "changelog", "체인지로그", "변경 이력", "릴리스 노트", "release note",
    "latest", "newest", "news", "뉴스", "근황",
)


def router_node(state: AgentState) -> dict:
    """
    질문을 vectorstore / web_search 로 분기한다.

    이전에는 이 판단에 LLM 을 1회 썼다. 그런데 이건 이분 분류이고, 기술 문서 챗봇에서는
    vectorstore 가 압도적 기본값이다. Gemini 무료 티어가 분당 5회뿐이라 이 1회가 아깝다.
    키워드 규칙으로 처리하고, LLM 라우팅이 필요하면 ROUTER_USE_LLM=true 로 되돌린다.
    """
    question = state["question"]
    lowered = question.lower()

    if any(sig in lowered for sig in _WEB_SIGNALS):
        route, how = "web_search", "rule"
    elif settings.router_use_llm:
        router_chain = router_prompt | json_llm | JsonOutputParser()
        try:
            result = router_chain.invoke({"question": question})
            route = result.get("route", "vectorstore")
            if route not in ("vectorstore", "web_search"):
                route = "vectorstore"
        except Exception as e:
            logger.warning("Router LLM failed, defaulting to vectorstore: %s", e)
            route = "vectorstore"
        how = "llm"
    else:
        route, how = "vectorstore", "rule"

    new_trace = state.get("trace", []) + [{"node": "router", "decision": route, "method": how}]
    return {"route": route, "trace": new_trace}


def retriever_node(state: AgentState) -> dict:
    question = state["question"]
    route = state.get("route", "vectorstore")
    
    # 리랭커를 쓰면 검색 단계에서 후보를 넓게 뽑아야 의미가 있다.
    # (리랭커는 이미 들어온 후보의 순서만 바꾼다. 애초에 빠뜨린 문서는 되찾지 못한다.)
    k = settings.reranker_candidates if reranker.is_enabled() else settings.retriever_top_k

    if route == "vectorstore":
        retriever = get_vector_store_manager().as_retriever(k=k)
        docs = retriever.invoke(question)
    else:
        docs = search_web(question, max_results=max(5, k))

    new_trace = state.get("trace", []) + [{"node": "retriever", "doc_count": len(docs), "k": k}]
    return {"documents": docs, "trace": new_trace}

async def grader_node(state: AgentState) -> dict:
    """
    검색된 문서를 걸러내고 순서를 정한다. 두 가지 경로가 있다.

    A) 리랭커 (RERANKER_ENABLED=true): cross-encoder 가 (질문, 문서) 쌍을 직접 점수화해
       상위 K개만 남긴다. LLM 호출 0회. 문서 "순서"까지 바로잡는다.
       Recall@1 이 70% -> 100% 로 오르지만 CPU 에서는 질문당 약 4.6초가 붙는다.

    B) LLM 배치 채점 (기본): 전체 문서를 번호 붙여 한 프롬프트에 넣고 1회만 호출한다.
       문서마다 1회씩 호출하던 이전 방식은 4개 문서에 4회가 들어, 분당 5회인
       Gemini 무료 티어를 질문 한 번에 초과했다.

    실측 비교는 BENCHMARK.md Phase 3 / Phase 5 참고.
    """
    question = state["question"]
    docs = state.get("documents", [])
    if not docs:
        new_trace = state.get("trace", []) + [{"node": "grader", "kept": 0, "dropped": 0}]
        return {"documents": [], "trace": new_trace}

    # --- 경로 A: cross-encoder 리랭커 (LLM 호출 0회) ---
    if reranker.is_enabled():
        kept_docs, scores = await asyncio.to_thread(
            reranker.rerank, question, docs, settings.retriever_top_k
        )
        new_trace = state.get("trace", []) + [{
            "node": "grader",
            "method": "reranker",
            "kept": len(kept_docs),
            "dropped": len(docs) - len(kept_docs),
            "top_score": round(scores[0], 4) if scores else None,
        }]
        return {"documents": kept_docs, "trace": new_trace}

    # --- 경로 B: LLM 채점 (전체 문서를 1회 호출로 배치 처리) ---
    # 이전에는 문서마다 1회씩 호출했다(4개 문서 = 4회). asyncio.gather 로 지연은 줄였지만
    # 호출 "횟수" 는 그대로여서 Gemini 무료 티어(분당 5회)를 질문 한 번에 초과했다.
    # 전체 문서를 번호 붙여 한 프롬프트에 넣고 관련 문서의 번호만 돌려받는다.
    numbered = "\n\n".join(
        f"[{i}]\n{d.page_content[:1500]}" for i, d in enumerate(docs)
    )
    chain = batch_grader_prompt | json_llm | JsonOutputParser()
    try:
        result = await chain.ainvoke({"question": question, "documents": numbered})
        raw = result.get("relevant", [])
        keep = {int(i) for i in raw if isinstance(i, (int, str)) and str(i).isdigit()}
        kept_docs = [d for i, d in enumerate(docs) if i in keep]
    except Exception as e:
        # 채점이 실패하면 문서를 버리지 않는다(재현율 우선). 조용히 넘기지는 않는다.
        logger.warning("Batch grader failed, keeping all %d docs: %s", len(docs), e)
        kept_docs = list(docs)

    new_trace = state.get("trace", []) + [
        {"node": "grader", "method": "llm_batch",
         "kept": len(kept_docs), "dropped": len(docs) - len(kept_docs)}
    ]
    return {"documents": kept_docs, "trace": new_trace}


async def generator_node(state: AgentState) -> dict:
    """
    최종 답변을 생성한다.

    invoke() 대신 astream() 을 쓰는 이유: LangGraph 의 stream_mode="messages" 는
    실제로 토큰을 흘리는 LLM 호출에서만 토큰 이벤트를 만들어낸다. astream 으로 호출해야
    api/routes/stream.py 가 생성되는 즉시 토큰을 프론트엔드로 밀어낼 수 있다.
    """
    question = state["question"]
    docs = state.get("documents", [])

    context = "\n\n".join([doc.page_content for doc in docs])

    generator_chain = generator_prompt | llm | StrOutputParser()
    parts = []
    async for piece in generator_chain.astream({"context": context, "question": question}):
        parts.append(piece)
    generation = "".join(parts)
    
    sources = []
    for doc in docs:
        src = doc.metadata.get("source", "unknown")
        if src not in sources:
            sources.append(src)
            
    new_trace = state.get("trace", []) + [{"node": "generator", "sources": sources}]
    return {
        "generation": generation, 
        "trace": new_trace,
        "messages": [AIMessage(content=generation)]
    }

def question_rewriter_node(state: AgentState) -> dict:
    question = state["question"]
    rewriter_chain = rewriter_prompt | llm | StrOutputParser()
    
    better_question = rewriter_chain.invoke({"question": question})
    
    rewrite_count = state.get("rewrite_count", 0) + 1
    new_trace = state.get("trace", []) + [{"node": "question_rewriter", "original": question, "new": better_question}]
    return {"question": better_question, "rewrite_count": rewrite_count, "trace": new_trace}

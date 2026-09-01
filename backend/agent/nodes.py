import re
import json
import asyncio
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.documents import Document
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState
from agent.prompts import (grader_prompt, batch_grader_prompt,
                           generator_prompt, rewriter_prompt, contextualize_prompt)
from store.vectorstore import get_vector_store_manager
from agent import reranker
from config import settings

logger = logging.getLogger(__name__)

# Initialize LLM with Gemini 2.5 Flash
llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-2.5-flash", google_api_key=settings.google_api_key, max_retries=3)
json_llm = ChatGoogleGenerativeAI(temperature=0, model="gemini-2.5-flash", google_api_key=settings.google_api_key, max_retries=3)

# 후속 질문이라고 전부 문맥이 필요한 것은 아니다.
# "Prefect 캐시 정책은?" 처럼 그 자체로 완결된 질문에 LLM 을 한 번 더 쓰는 것은 낭비다.
# 지시어·대명사·생략이 보일 때만 문맥화한다. 라우터를 규칙으로 내린 것과 같은 방식이다.
#
# 판정은 보수적이어야 한다. 잘못 건너뛰면 "그거 다시 설명해줘" 가 그대로 검색어가 되어
# 답이 무너진다. 반대로 불필요하게 호출하는 것은 비용만 든다. 그래서 애매하면 호출한다.
_ANAPHORA_KO = (
    "그거", "그건", "그것", "그게", "그중", "그 중",
    "저거", "저건", "저것", "이거", "이건", "이것", "이게",
    "방금", "아까", "위에", "앞서", "이전", "직전",
    "말한", "얘기한", "설명한", "언급한", "알려준", "답한",
    "다시", "자세히", "더 ", "예시", "그럼", "그러면", "왜 ",
)
_ANAPHORA_EN = re.compile(
    r"\b(it|its|that|this|these|those|them|they|there|"
    r"again|above|previous|earlier|former|latter|"
    r"more|else|instead|also|why)\b",
    re.I,
)
# 앞 대화의 항목을 가리키는 생략형. 지시어가 없어도 앞 맥락 없이는 성립하지 않는다.
# "What about the second one?" 이 대표적이다. 이런 질문을 그대로 검색하면
# 관련 문서가 0건이 되고 재작성 루프가 돌아, 아낀 1회보다 더 많은 호출을 쓴다.
_ELLIPTIC_EN = re.compile(
    r"\b(what|how)\s+about\b|"
    r"\b(the\s+)?(first|second|third|fourth|last|next|other|rest)\s+(one|ones)?\b",
    re.I,
)
# 생략형 질문의 길이 기준. "왜?", "더 자세히" 처럼 짧으면 앞 맥락 없이는 성립하지 않는다.
_ELLIPSIS_MAX_CHARS = 12


def needs_context(question: str) -> bool:
    """이 질문이 앞 대화에 기대고 있는가. 애매하면 True(=LLM 호출)를 낸다."""
    q = (question or "").strip()
    if len(q) < _ELLIPSIS_MAX_CHARS:
        return True
    low = q.lower()
    if any(w in low for w in _ANAPHORA_KO):
        return True
    return bool(_ANAPHORA_EN.search(low) or _ELLIPTIC_EN.search(low))


def contextualize_node(state: AgentState) -> dict:
    question = state["question"]
    messages = state.get("messages", [])

    if len(messages) <= 1:
        standalone_question, method = question, "first"
    elif not needs_context(question):
        # 후속 질문이지만 그 자체로 완결돼 있다. LLM 0회.
        standalone_question, method = question, "rule"
    else:
        # 마지막 항목은 방금 들어온 질문이므로 제외하고, 그 앞에서 최근 N개만 쓴다.
        history = messages[:-1][-settings.history_window:]
        chat_history = "\n".join(
            f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content}" for m in history
        )
        chain = contextualize_prompt | llm | StrOutputParser()
        standalone_question = chain.invoke({"chat_history": chat_history, "question": question})
        method = "llm"

    new_trace = state.get("trace", []) + [
        {"node": "contextualize", "standalone": standalone_question, "method": method}
    ]
    return {"question": standalone_question, "trace": new_trace}


def retriever_node(state: AgentState) -> dict:
    question = state["question"]

    # 리랭커를 쓰면 검색 단계에서 후보를 넓게 뽑아야 의미가 있다.
    # (리랭커는 이미 들어온 후보의 순서만 바꾼다. 애초에 빠뜨린 문서는 되찾지 못한다.)
    k = settings.reranker_candidates if reranker.is_enabled() else settings.retriever_top_k

    retriever = get_vector_store_manager().as_retriever(k=k)
    docs = retriever.invoke(question)

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

# 정상적인 질문은 이보다 훨씬 짧다. 넘으면 설명문이 섞였다고 본다.
_MAX_REWRITE_CHARS = 300
_LABEL_RE = re.compile(r"^(?:improved|revised|rewritten|new)\s+question\s*:\s*(.*)$", re.I)


def _clean_rewritten_question(raw: str, fallback: str) -> str:
    """
    재작성 결과에서 질문 한 줄만 뽑는다. 뽑지 못하면 원래 질문을 그대로 쓴다.

    프롬프트로 형식을 지시하지만 LLM 출력은 확률적이라 어긋날 수 있고, 어긋나면
    설명문 전체가 다음 검색 질의가 된다. 실제로 1,500자짜리 설명문이 검색어로
    들어간 적이 있다. 오염된 질의로 검색하느니 원문으로 한 번 더 검색하는 편이 낫다 —
    재검색 횟수는 graph.py 의 순환 방지가 2회로 막아 준다.
    """
    text = (raw or "").strip()
    if not text:
        return fallback

    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.replace("**", "").strip()

    lines = [ln.strip(" \t-*>#") for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return fallback

    # "Improved Question:" 같은 라벨이 있으면 그 뒤(없으면 다음 줄)를 채택한다.
    for i, ln in enumerate(lines):
        m = _LABEL_RE.match(ln)
        if m:
            cand = m.group(1).strip() or (lines[i + 1] if i + 1 < len(lines) else "")
            if cand:
                lines = [cand]
            break

    candidate = next((ln for ln in lines if ln.endswith("?")), lines[0])
    if not candidate or len(candidate) > _MAX_REWRITE_CHARS:
        return fallback
    return candidate


def question_rewriter_node(state: AgentState) -> dict:
    question = state["question"]

    rewriter_chain = rewriter_prompt | llm | StrOutputParser()
    raw = rewriter_chain.invoke({"question": question})
    better_question = _clean_rewritten_question(raw, question)

    if better_question == question:
        logger.warning("재작성 결과를 쓸 수 없어 원 질문을 유지합니다: %r", (raw or "")[:120])

    rewrite_count = state.get("rewrite_count", 0) + 1
    new_trace = state.get("trace", []) + [{
        "node": "question_rewriter",
        "original": question,
        "new": better_question,
        # 모델이 형식을 어겨 걸러낸 경우를 화면과 로그에서 구분할 수 있게 남긴다.
        "sanitized": better_question != (raw or "").strip(),
    }]
    return {"question": better_question, "rewrite_count": rewrite_count, "trace": new_trace}

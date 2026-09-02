"""
생성 단계 개선의 효과를 잰다. 검색은 건드리지 않는다.

설계
----
검색 결과를 **두 설정에 동일하게 고정** 입력한다. 그래야 답변 차이가 생성 단계에서만
나온 것이 된다. 채점기(grader)는 우회한다. 변수를 줄이고 LLM 호출도 아낀다.

  A) current   nodes.py 현행: "\\n\\n".join(page_content) + 현행 338자 지시문
  B) improved  인접 청크 병합 + 출처 라벨 + 발췌 명시 + 개선 지시문

지표 (전부 자동, 사람 판단 불필요)
  coverage      답변이 담은 사실 표식 비율. 표식은 answer_keys_generation.json
  ctx_chars     LLM 에 들어간 컨텍스트 길이 — 인접 병합의 중복 제거 효과
  ans_chars     답변 길이
  src_junk      "Sources:" 류 목록을 답변에 덧붙였는가 (UI 가 이미 그리므로 중복)

LLM 호출: 질문당 설정 2개 = 6문항 x 2 = 12회. 무료 티어 분당 5회를 넘지 않도록
호출 간 13초를 쉰다.

    docker compose exec -T backend-api python eval/run_generation_eval.py
"""
import asyncio
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.output_parsers import StrOutputParser        # noqa: E402
from langchain_core.prompts import ChatPromptTemplate            # noqa: E402

from agent.nodes import llm                                      # noqa: E402
from agent.prompts import generator_prompt                       # noqa: E402
from store.vectorstore import get_vector_store_manager           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = "/app/data/generation_eval.json"
K = 4
SLEEP = 13          # 분당 5회 제한. 12회 x 13초 = 약 2분 40초


# --------------------------------------------------------------------------
# 개선안 구현 (측정 후 nodes.py 로 옮긴다)
# --------------------------------------------------------------------------
def _strip_overlap(a: str, b: str, max_probe: int = 250) -> str:
    """
    a 의 꼬리와 b 의 머리가 겹치면 b 에서 겹친 만큼 잘라낸다.

    chunk_overlap=50 때문에 연속 청크는 서로를 반복한다. 그대로 이어붙이면
    LLM 이 같은 문장을 두 번 본다. 실제로 sessions.mdx 0·1번 청크는
    "In the session view you can:" 를 둘 다 갖고 있다.
    """
    limit = min(len(a), len(b), max_probe)
    for n in range(limit, 19, -1):          # 20자 미만의 우연한 일치는 무시
        if a[-n:] == b[:n]:
            return b[n:]
    return b


def merge_adjacent(docs):
    """
    같은 파일의 연속된 청크를 하나로 잇는다. 검색 순위는 그룹의 첫 청크 것을 쓴다.
    """
    groups = []      # [ {file, first_rank, pieces:[(idx, text)]} ]
    for rank, d in enumerate(docs):
        path = d.metadata.get("file_path") or d.metadata.get("source", "?")
        try:
            idx = int(float(d.metadata.get("chunk_in_doc", -1)))
        except (TypeError, ValueError):
            idx = -1
        for g in groups:
            if g["file"] != path or idx < 0:
                continue
            if any(abs(idx - i) == 1 for i, _ in g["pieces"]):
                g["pieces"].append((idx, d.page_content))
                break
        else:
            groups.append({"file": path, "rank": rank, "pieces": [(idx, d.page_content)]})

    merged = []
    for g in groups:
        pieces = sorted(g["pieces"])
        text = pieces[0][1]
        for _, nxt in pieces[1:]:
            text += _strip_overlap(text, nxt)
        merged.append((g["file"], text, len(pieces)))
    return merged


def build_context_improved(docs) -> str:
    parts = []
    for i, (path, text, n) in enumerate(merge_adjacent(docs), 1):
        parts.append(f"[Excerpt {i} — {path}]\n{text}")
    return "\n\n".join(parts)


def build_context_current(docs) -> str:
    return "\n\n".join(d.page_content for d in docs)            # nodes.py:173 현행


improved_prompt = ChatPromptTemplate.from_template(
    """You are an expert technical assistant for developer documentation.

Answer the question using only the excerpts below. Each excerpt is labeled with the \
source file it came from. These are partial extracts, not complete documents.

Rules:
- Ground every statement in the excerpts. Do not add outside knowledge.
- If the excerpts answer the question only in part, give that part, then state plainly \
what they do not cover.
- A caveat inside one excerpt (for example "this document is outdated") applies to that \
excerpt only. It does not stop you from using the others.
- If no excerpt is relevant, say so directly.
- Use fenced code blocks for code and numbered steps for procedures.
- Do not append a list of sources; the interface already displays them.

Excerpts:
{context}

Question: {question}

Answer:"""
)


# --------------------------------------------------------------------------
# 측정
# --------------------------------------------------------------------------
_SRC_JUNK = re.compile(r"^\s*(\*\*)?(sources?|references?)(\*\*)?\s*:?\s*$", re.I | re.M)


def coverage(answer: str, markers) -> float:
    low = answer.lower()
    return sum(1 for m in markers if m.lower() in low) / (len(markers) or 1)


async def main():
    with open(os.path.join(HERE, "answer_keys_generation.json"), encoding="utf-8") as f:
        spec = json.load(f)
    questions = spec["questions"]

    retriever = get_vector_store_manager().as_retriever(k=K)

    # 1) 검색 1회 + 표식 존재 검증 --------------------------------------------
    fixed, bad = {}, []
    for qid, q in questions.items():
        docs = retriever.invoke(q["question"])
        blob = " ".join(d.page_content for d in docs).lower()
        missing = [m for m in q["markers"] if m.lower() not in blob]
        if missing:
            bad.append((qid, missing))
        fixed[qid] = docs

    if bad:
        print("!! 검색된 청크에 없는 표식이 있습니다. 이대로면 생성기가 아니라")
        print("   검색기를 재게 됩니다. 표식을 고친 뒤 다시 실행하세요.\n")
        for qid, missing in bad:
            print(f"   {qid}: {missing}")
        return

    print(f"표식 검증 통과 · {len(fixed)}문항 · 청크 고정 완료 (LLM 0회)\n")

    variants = {
        "current":  (build_context_current,  generator_prompt),
        "improved": (build_context_improved, improved_prompt),
    }

    rows, calls = [], 0
    for qid, q in questions.items():
        docs = fixed[qid]
        for name, (build, prompt) in variants.items():
            ctx = build(docs)
            if calls:
                time.sleep(SLEEP)
            t0 = time.perf_counter()
            answer = await (prompt | llm | StrOutputParser()).ainvoke(
                {"context": ctx, "question": q["question"]}
            )
            calls += 1
            rows.append({
                "id": qid, "variant": name,
                "coverage": coverage(answer, q["markers"]),
                "ctx_chars": len(ctx),
                "ans_chars": len(answer),
                "src_junk": bool(_SRC_JUNK.search(answer)),
                "secs": round(time.perf_counter() - t0, 2),
                "answer": answer,
            })
            print(f"  {qid} {name:<9} 커버리지 {rows[-1]['coverage']:5.0%}  "
                  f"컨텍스트 {len(ctx):>5}자  답변 {len(answer):>5}자  "
                  f"출처중복 {'Y' if rows[-1]['src_junk'] else 'N'}  {rows[-1]['secs']:>5.1f}s")

    print(f"\nGemini 호출 {calls}회\n" + "=" * 74)
    print(f"{'설정':<12}{'커버리지':>10}{'컨텍스트':>12}{'답변길이':>10}{'출처중복':>10}{'지연':>8}")
    for name in variants:
        r = [x for x in rows if x["variant"] == name]
        n = len(r)
        print(f"{name:<12}{sum(x['coverage'] for x in r)/n:>9.1%}"
              f"{sum(x['ctx_chars'] for x in r)//n:>11,}자"
              f"{sum(x['ans_chars'] for x in r)//n:>9,}자"
              f"{sum(1 for x in r if x['src_junk']):>8}/{n}"
              f"{sum(x['secs'] for x in r)/n:>7.1f}s")

    print("\n=== 문항별 커버리지 ===")
    for qid in questions:
        c = {x["variant"]: x["coverage"] for x in rows if x["id"] == qid}
        print(f"  {qid}  current {c['current']:5.0%}  ->  improved {c['improved']:5.0%}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"k": K, "calls": calls, "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

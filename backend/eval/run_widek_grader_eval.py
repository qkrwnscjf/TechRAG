"""
"후보를 30개로 넓히면 채점기가 묻힌 정답을 골라내는가" 를 검증한다.

배경 (Phase 33)
---------------
prefect-03 / prefect-04 는 k=8 까지 넓혀도 정답 문서가 들어오지 않았다.
100위까지 열어 보니 정답 `docs/v3/concepts/tasks.mdx` 는 9~28위에 있었다.

    prefect-03 EN  9위     prefect-03 KO  15위
    prefect-04 EN 19위     prefect-04 KO  28위

k=30 이면 정답 포함률이 100% 가 된다. 그러나 후보에 있는 것과 채점기가 골라내는
것은 다르다. 채점기는 이미 배치 1회이므로 **LLM 호출 횟수는 늘지 않는다.**
프롬프트가 약 6,000자 -> 45,000자로 늘어날 뿐이다.

그 프롬프트에서 채점 정확도가 유지되는지는 **알 수 없다.** 그것을 잰다.

설계
----
채점기를 재구현하지 않고 운영 `grader_node()` 를 그대로 호출한다.
재구현하면 운영과 다른 것을 재게 된다. (Phase 32 와 같은 원칙)

1단계: 실패 4건만 k=30 으로 채점. 정답이 살아남지 않으면 **가설 기각, 즉시 종료.**
       LLM 4회.
2단계: 1단계 성공 시에만 회귀 확인. 별도 스크립트.

    docker compose exec -T backend-api python eval/run_widek_grader_eval.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.nodes import grader_node                       # noqa: E402  운영 코드 그대로
from store.vectorstore import get_vector_store_manager    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = "/app/data/widek_grader_eval.json"
WIDE_K = 30
SLEEP = 13          # 분당 5회 제한

TARGETS = [("prefect-03", "ko"), ("prefect-03", "en"),
           ("prefect-04", "ko"), ("prefect-04", "en")]


async def main():
    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        golden = {q["id"]: q for q in json.load(f)["questions"]}

    retriever = get_vector_store_manager().as_retriever(k=WIDE_K)

    print(f"1단계 · 실패 4건 · k={WIDE_K} · 운영 grader_node() 호출 · Gemini 4회\n")

    rows, calls = [], 0
    for qid, lang in TARGETS:
        q = golden[qid]
        question = q[f"question_{lang}"]
        gold = set(q["gold_paths"])

        docs = retriever.invoke(question)
        gold_pos = [i for i, d in enumerate(docs)
                    if d.metadata.get("file_path") in gold]
        prompt_chars = sum(len(d.page_content[:1500]) for d in docs)

        if not gold_pos:
            print(f"  {qid} {lang}: k={WIDE_K} 후보에도 정답 없음 — 채점 생략")
            rows.append({"id": qid, "lang": lang, "in_candidates": False})
            continue

        if calls:
            time.sleep(SLEEP)
        t0 = time.perf_counter()
        out = await grader_node({"question": question, "documents": docs, "trace": []})
        calls += 1
        secs = time.perf_counter() - t0

        kept = out["documents"]
        kept_paths = [d.metadata.get("file_path") for d in kept]
        survived = any(p in gold for p in kept_paths)
        rank_in_kept = next((i for i, p in enumerate(kept_paths, 1) if p in gold), None)

        rows.append({
            "id": qid, "lang": lang, "in_candidates": True,
            "gold_rank_in_candidates": gold_pos[0] + 1,
            "candidates": len(docs), "prompt_chars": prompt_chars,
            "kept": len(kept), "survived": survived,
            "rank_in_kept": rank_in_kept, "secs": round(secs, 1),
            "kept_paths": kept_paths[:8],
        })
        mark = "O 생존" if survived else "X 탈락"
        print(f"  {qid} {lang}  후보 {gold_pos[0]+1}위/{len(docs)}  "
              f"프롬프트 {prompt_chars:,}자  채점 {len(kept)}개 유지  "
              f"{mark}"
              + (f" (유지본 {rank_in_kept}번째)" if rank_in_kept else "")
              + f"  {secs:.1f}s")

    graded = [r for r in rows if r.get("in_candidates")]
    n_ok = sum(1 for r in graded if r["survived"])
    print(f"\nGemini 호출 {calls}회")
    print("=" * 66)
    print(f"정답 생존 {n_ok}/{len(graded)}")
    if graded:
        print(f"평균 채점 지연 {sum(r['secs'] for r in graded)/len(graded):.1f}s "
              f"(k=5 기준 프롬프트의 약 6배 길이)")

    print("\n판정:", "2단계(회귀 확인)로 진행할 근거 있음"
          if n_ok == len(graded) and graded else
          "가설 기각 — 후보에 넣어도 채점기가 골라내지 못한다")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"wide_k": WIDE_K, "calls": calls, "rows": rows},
                  f, ensure_ascii=False, indent=2)
    print(f"저장: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

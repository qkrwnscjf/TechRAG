"""
리랭커(cross-encoder) 효과 측정. LLM 호출 0회.

배경
  Phase 23 에서 R@1 79.6% / R@5 92.6% 로, **정답이 후보에는 있는데 1위가 아닌 질의가
  13.0%p** 있음이 드러났다. 리랭커는 새 문서를 찾는 도구가 아니라 가져온 것의
  순서를 바로잡는 도구이므로, 이 여유가 정확히 리랭커의 표적이다.

  Phase 3 의 측정(Recall@1 70% -> 100%)은 자체 문서 31청크 · 질문 10개 기준이었다.
  지금 색인은 7,712청크다. 조건이 달라 그대로 믿을 수 없어 다시 잰다.

비교
  dense@5              현행 (bi-encoder 상위 5)
  rerank(top10) -> 5   후보 10개를 cross-encoder 로 재정렬
  rerank(top20) -> 5   후보를 넓히면 더 나아지는가

    docker compose exec -d backend-api python eval/run_reranker_eval.py
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import reranker                                  # noqa: E402
from store.vectorstore import get_vector_store_manager      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = "/app/data/reranker_eval.log"
OUT = "/app/data/reranker_eval.json"
K = 5
DEPTHS = (10, 20)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def first_hit(docs, gold):
    for i, d in enumerate(docs[:K], start=1):
        if d.metadata.get("file_path") in gold:
            return i
    return None


def summarize(ranks):
    n = len(ranks) or 1
    at = lambda m: sum(1 for r in ranks if r and r <= m) / n      # noqa: E731
    return {"n": len(ranks), "r1": at(1), "r3": at(3), "r5": at(K),
            "mrr": sum(1.0 / r for r in ranks if r) / n}


def line(label, s):
    return (f"  {label:<20} n={s['n']:>3}  R@1 {s['r1']:6.1%}  R@3 {s['r3']:6.1%}  "
            f"R@{K} {s['r5']:6.1%}  MRR {s['mrr']:.3f}")


def main():
    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        questions = json.load(f)["questions"]

    queries = [(q["id"], q["source"], "ko", q["question_ko"], set(q["gold_paths"])) for q in questions]
    queries += [(q["id"], q["source"], "en", q["question_en"], set(q["gold_paths"])) for q in questions]

    log(f"START  질의 {len(queries)}건 · 후보 폭 {DEPTHS} · k={K}")

    retriever = get_vector_store_manager().as_retriever(k=max(DEPTHS))

    # 모델을 미리 올린다(다운로드 포함). 첫 질의에 로딩 시간이 섞이지 않게.
    t0 = time.time()
    reranker._get_model()
    log(f"리랭커 모델 로드 완료 {time.time()-t0:.0f}초")

    rows, rr_times = [], {d: [] for d in DEPTHS}
    for n, (qid, source, lang, text, gold) in enumerate(queries, start=1):
        t = time.time()
        cands = retriever.invoke(text)
        dense_ms = (time.time() - t) * 1000

        row = {"id": qid, "source": source, "lang": lang, "query": text,
               "gold": sorted(gold), "dense": first_hit(cands, gold),
               "dense_ms": round(dense_ms)}

        for depth in DEPTHS:
            t = time.time()
            ranked, _ = reranker.rerank(text, cands[:depth], K)
            ms = (time.time() - t) * 1000
            rr_times[depth].append(ms)
            row[f"rerank{depth}"] = first_hit(ranked, gold)
            row[f"rerank{depth}_ms"] = round(ms)

        rows.append(row)
        if n % 10 == 0:
            log(f"  {n}/{len(queries)}")

    methods = ["dense"] + [f"rerank{d}" for d in DEPTHS]

    log("=" * 74)
    for lang in ("ko", "en"):
        sub = [r for r in rows if r["lang"] == lang]
        log(f"=== {lang.upper()} ===")
        for m in methods:
            log(line(m, summarize([r[m] for r in sub])))

    log("=== 전체 (ko+en) ===")
    overall = {m: summarize([r[m] for r in rows]) for m in methods}
    for m in methods:
        log(line(m, overall[m]))

    d = overall["dense"]
    for depth in DEPTHS:
        f_ = overall[f"rerank{depth}"]
        log(f"=== rerank{depth} − dense ===")
        for key, lab in (("r1", "Recall@1"), ("r3", "Recall@3"), ("r5", f"Recall@{K}")):
            log(f"  {lab:<10} {f_[key]-d[key]:+.1%}")
        log(f"  {'MRR':<10} {f_['mrr']-d['mrr']:+.3f}")

    log("=== 지연 (질의당) ===")
    log(f"  dense 검색      중앙 {statistics.median(r['dense_ms'] for r in rows):.0f}ms")
    for depth in DEPTHS:
        v = rr_times[depth]
        log(f"  rerank({depth:>2})     중앙 {statistics.median(v):.0f}ms  "
            f"최소 {min(v):.0f}  최대 {max(v):.0f}")

    # 상한 대비 회수율: dense 의 R@5 가 리랭커가 도달할 수 있는 천장이다
    ceiling = d["r5"] - d["r1"]
    for depth in DEPTHS:
        got = overall[f"rerank{depth}"]["r1"] - d["r1"]
        log(f"  rerank({depth:>2}) 가 회수한 여유: {got:+.1%} / 상한 {ceiling:+.1%}"
            f"  ({got/ceiling:.0%})" if ceiling else "")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"k": K, "depths": list(DEPTHS), "overall": overall,
                   "rerank_ms": {str(k): v for k, v in rr_times.items()},
                   "rows": rows}, f, ensure_ascii=False, indent=2)
    log(f"DONE  결과 저장: {OUT}")


if __name__ == "__main__":
    main()

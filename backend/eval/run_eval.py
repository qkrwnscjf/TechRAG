"""
검색 품질 평가. LLM 을 호출하지 않는다 — 임베딩(로컬)과 Pinecone 조회만 쓴다.

그래서 Gemini 하루 20회 제한과 무관하게 몇 번이든 돌릴 수 있다.
답변 품질이 아니라 "정답 문서를 상위 k 안에 가져오는가" 만 본다.

    docker compose exec -T backend-api python eval/run_eval.py
    docker compose exec -T backend-api python eval/run_eval.py --k 10 --lang ko

지표:
  Recall@k  정답 문서의 청크가 상위 k 안에 하나라도 있으면 1
  MRR       첫 정답이 나온 순위의 역수 평균

nDCG 는 넣지 않았다. 질문당 정답 문서가 하나이고 관련성이 이진값이라
MRR 이 담지 못하는 정보를 더하지 못한다. 지표 수를 늘리는 것 자체는 의미가 없다.
"""
import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.vectorstore import get_vector_store_manager  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def first_hit_rank(docs, gold_paths):
    """정답 문서가 처음 나온 1-based 순위. 없으면 None."""
    for i, d in enumerate(docs, start=1):
        if d.metadata.get("file_path") in gold_paths:
            return i
    return None


def evaluate(questions, lang, retriever):
    rows = []
    for q in questions:
        query = q[f"question_{lang}"]
        gold = set(q["gold_paths"])

        t0 = time.perf_counter()
        docs = retriever.invoke(query)
        elapsed = (time.perf_counter() - t0) * 1000

        rows.append({
            "id": q["id"],
            "source": q["source"],
            "lang": lang,
            "query": query,
            "rank": first_hit_rank(docs, gold),
            "ms": elapsed,
            "retrieved": [d.metadata.get("file_path", "?") for d in docs],
            "gold": sorted(gold),
        })
    return rows


def summarize(rows, k):
    def recall_at(n):
        return sum(1 for r in rows if r["rank"] and r["rank"] <= n) / len(rows)

    return {
        "n": len(rows),
        "recall@1": recall_at(1),
        "recall@3": recall_at(3),
        "recall@k": recall_at(k),
        "mrr": sum(1.0 / r["rank"] for r in rows if r["rank"]) / len(rows),
        "median_ms": statistics.median(r["ms"] for r in rows),
    }


def fmt(s, k):
    return (f"n={s['n']:>3}  R@1 {s['recall@1']:6.1%}  R@3 {s['recall@3']:6.1%}  "
            f"R@{k} {s['recall@k']:6.1%}  MRR {s['mrr']:.3f}  "
            f"질의지연 중앙값 {s['median_ms']:.0f}ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5, help="검색 깊이")
    ap.add_argument("--lang", choices=["ko", "en", "both"], default="both")
    ap.add_argument("--golden", default=os.path.join(HERE, "golden_set.json"))
    ap.add_argument("--out", help="질문별 결과를 JSON 으로 저장할 경로")
    args = ap.parse_args()

    with open(args.golden, encoding="utf-8") as f:
        data = json.load(f)
    questions = data["questions"]
    langs = ["ko", "en"] if args.lang == "both" else [args.lang]

    print(f"골든셋 {len(questions)}문항 · k={args.k} · 언어 {'/'.join(langs)}")
    print(f"코퍼스 {data['corpus']['total_chunks']:,}청크\n")

    retriever = get_vector_store_manager().as_retriever(k=args.k)

    all_rows = []
    for lang in langs:
        rows = evaluate(questions, lang, retriever)
        all_rows += rows

        print(f"=== {lang.upper()} ===")
        print("  전체       ", fmt(summarize(rows, args.k), args.k))
        by_source = defaultdict(list)
        for r in rows:
            by_source[r["source"]].append(r)
        for src in sorted(by_source):
            print(f"  {src:<11}", fmt(summarize(by_source[src], args.k), args.k))
        print()

    if len(langs) == 2:
        ko = summarize([r for r in all_rows if r["lang"] == "ko"], args.k)
        en = summarize([r for r in all_rows if r["lang"] == "en"], args.k)
        print("=== 교차언어 격차 (EN - KO) ===")
        for key in ("recall@1", "recall@3", "recall@k"):
            label = f"recall@{args.k}" if key == "recall@k" else key
            print(f"  {label:<10} {en[key] - ko[key]:+.1%}")
        print(f"  {'mrr':<10} {en['mrr'] - ko['mrr']:+.3f}\n")

    misses = [r for r in all_rows if r["rank"] is None]
    if misses:
        print(f"=== 정답을 못 찾은 질의 {len(misses)}건 ===")
        for r in misses:
            print(f"  [{r['lang']}] {r['id']}  {r['query'][:52]}")
            print(f"        정답 {r['gold']}")
            print(f"        검색 {r['retrieved'][:3]}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"k": args.k, "rows": all_rows}, f, ensure_ascii=False, indent=2)
        print(f"\n질문별 결과 저장: {args.out}")


if __name__ == "__main__":
    main()

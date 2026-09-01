"""
소스 메타데이터 필터의 효과를 잰다. LLM 호출 0회.

현재는 질문 하나가 7,712청크 전체를 대상으로 검색한다. 질문에 "Prefect" 가
들어 있으면 그 소스만 보면 되는데도 그렇다. 후보 풀을 줄이면 정밀도가 오를 수 있다.

  dense        현행 (필터 없음)
  filtered     소스가 판정되면 그 소스로 Pinecone 메타데이터 필터

전체 비교와 함께 **필터가 실제로 걸린 질의만** 따로 본다.
필터가 안 걸린 질의는 두 방식이 같은 결과를 내므로, 섞어 놓으면 효과가 희석된다.

    docker compose exec -T backend-api python eval/run_filter_eval.py
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import store.db as db                                       # noqa: E402
from store.vectorstore import get_vector_store_manager      # noqa: E402
from eval.source_filter import build_index, route           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
K = 5


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
    return (f"  {label:<22} n={s['n']:>3}  R@1 {s['r1']:6.1%}  R@3 {s['r3']:6.1%}  "
            f"R@{K} {s['r5']:6.1%}  MRR {s['mrr']:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/app/data/filter_eval.json")
    args = ap.parse_args()

    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        questions = json.load(f)["questions"]

    sources = [d["url"] for d in db.get_documents()]
    index = build_index(sources)
    print("=== 소스별 도출 키워드 ===")
    for url, keys in index.items():
        print(f"  {sorted(keys)}  <- {url}")

    mgr = get_vector_store_manager()
    plain = mgr.as_retriever(k=K)

    rows = []
    t0 = time.time()
    for q in questions:
        for lang in ("ko", "en"):
            text = q[f"question_{lang}"]
            gold = set(q["gold_paths"])
            target = route(text, index)

            base = plain.invoke(text)
            if target:
                filt = mgr.store.as_retriever(
                    search_kwargs={"k": K, "filter": {"source": target}}
                ).invoke(text)
            else:
                filt = base

            rows.append({
                "id": q["id"], "source": q["source"], "lang": lang, "query": text,
                "routed": target, "routed_ok": (target is not None),
                "dense": first_hit(base, gold),
                "filtered": first_hit(filt, gold),
            })
    print(f"\n질의 {len(rows)}건 · {time.time()-t0:.0f}초\n")

    matched = [r for r in rows if r["routed_ok"]]
    print(f"=== 라우팅 ===")
    print(f"  소스 판정 성공  {len(matched)}/{len(rows)}  ({len(matched)/len(rows):.0%})")
    wrong = [r for r in matched
             if r["routed"].split("/")[-1].lower().replace("-docs", "") not in r["source"]]
    print(f"  잘못 판정       {len(wrong)}건")
    for r in wrong:
        print(f"    {r['id']} ({r['source']}) -> {r['routed']}")

    print(f"\n=== 전체 {len(rows)}질의 ===")
    print(line("dense (현행)", summarize([r["dense"] for r in rows])))
    print(line("filtered", summarize([r["filtered"] for r in rows])))

    print(f"\n=== 필터가 걸린 질의만 ({len(matched)}건) ===")
    d = summarize([r["dense"] for r in matched])
    f_ = summarize([r["filtered"] for r in matched])
    print(line("dense", d))
    print(line("filtered", f_))
    print("\n  차이")
    for key, lab in (("r1", "Recall@1"), ("r3", "Recall@3"), ("r5", f"Recall@{K}")):
        print(f"    {lab:<10} {f_[key]-d[key]:+.1%}")
    print(f"    {'MRR':<10} {f_['mrr']-d['mrr']:+.3f}")

    changed = [r for r in matched if (r["dense"] or 99) != (r["filtered"] or 99)]
    if changed:
        print(f"\n=== 순위가 바뀐 질의 {len(changed)}건 ===")
        for r in changed:
            arrow = "개선" if (r["filtered"] or 99) < (r["dense"] or 99) else "악화"
            print(f"  [{r['lang']}] {r['id']}  {r['dense']} -> {r['filtered']}  ({arrow})")
            print(f"        {r['query'][:62]}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"k": K, "sources": {u: sorted(v) for u, v in index.items()},
                   "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()

"""
dense(현행) vs BM25 단독 vs RRF 융합을 같은 골든셋으로 나란히 측정한다.

배경
  Phase 3 에서 하이브리드 검색을 걷어냈다. 이유는 `pinecone-text` 의 BM25 가
  영어 사전학습 IDF 를 쓰기 때문이었다 — 방식이 아니라 파라미터의 문제였다.
  Phase 23 에서 관측한 실패(개념 문서가 예제 문서에 밀림)는 전형적인 어휘 문제라
  코퍼스에서 직접 학습한 BM25 라면 다를 수 있다. 그것을 확인한다.

  LLM 호출 0회. 임베딩(로컬)과 Pinecone 조회만 쓴다.

    docker compose exec -T backend-api python eval/run_hybrid_eval.py
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings                                    # noqa: E402
from pinecone import Pinecone                                  # noqa: E402
from store.vectorstore import get_vector_store_manager         # noqa: E402
from eval.bm25 import BM25, rrf                                # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = "/app/data/corpus_dump.json"
FUSE_DEPTH = 20          # 융합에 넣을 각 검색기의 상위 개수
K = 5                    # 최종 평가 깊이


def load_corpus():
    """Pinecone 에 있는 청크 전량을 내려받아 캐시한다. BM25 는 원문이 있어야 한다."""
    if os.path.exists(DUMP):
        with open(DUMP, encoding="utf-8") as f:
            docs = json.load(f)
        print(f"코퍼스 캐시 사용: {len(docs):,}청크")
        return docs

    idx = Pinecone(api_key=settings.pinecone_api_key).Index(settings.pinecone_index_name)
    ids = []
    for page in idx.list():
        ids.extend(page)
    print(f"Pinecone 청크 {len(ids):,}개 내려받는 중…")

    docs, t0 = [], time.time()
    for i in range(0, len(ids), 100):
        got = idx.fetch(ids=ids[i:i + 100])
        vecs = got.vectors if hasattr(got, "vectors") else got["vectors"]
        for vid, v in vecs.items():
            md = v.metadata if hasattr(v, "metadata") else v["metadata"]
            docs.append({
                "id": vid,
                "source": md.get("source", ""),
                "file_path": md.get("file_path", ""),
                "text": md.get("text", ""),
            })
        if (i // 100) % 20 == 0:
            print(f"  {min(i+100, len(ids)):,}/{len(ids):,}")
    print(f"  완료 {time.time()-t0:.0f}초")

    with open(DUMP, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)
    return docs


def first_hit(paths, gold):
    for i, p in enumerate(paths[:K], start=1):
        if p in gold:
            return i
    return None


def summarize(ranks):
    n = len(ranks)
    at = lambda m: sum(1 for r in ranks if r and r <= m) / n      # noqa: E731
    return {"n": n, "r1": at(1), "r3": at(3), "r5": at(K),
            "mrr": sum(1.0 / r for r in ranks if r) / n}


def row(label, s):
    return (f"  {label:<12} n={s['n']:>3}  R@1 {s['r1']:6.1%}  R@3 {s['r3']:6.1%}  "
            f"R@{K} {s['r5']:6.1%}  MRR {s['mrr']:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/app/data/hybrid_eval.json")
    args = ap.parse_args()

    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        golden = json.load(f)
    questions = golden["questions"]

    corpus = load_corpus()
    texts = [d["text"] for d in corpus]
    paths = [d["file_path"] for d in corpus]
    # dense 결과(page_content)를 코퍼스 위치로 되돌리기 위한 색인
    text_to_idx = {}
    for i, t in enumerate(texts):
        text_to_idx.setdefault(t, i)

    print("BM25 색인 구축 중…")
    t0 = time.time()
    bm = BM25(texts)
    print(f"  {len(texts):,}문서 · 어휘 {len(bm.idf):,} · {time.time()-t0:.1f}초\n")

    retriever = get_vector_store_manager().as_retriever(k=FUSE_DEPTH)

    queries = [(q["id"], q["source"], "ko", q["question_ko"], set(q["gold_paths"])) for q in questions]
    queries += [(q["id"], q["source"], "en", q["question_en"], set(q["gold_paths"])) for q in questions]

    rows = []
    for qid, source, lang, text, gold in queries:
        dense_docs = retriever.invoke(text)
        dense_idx, dense_paths = [], []
        for d in dense_docs:
            dense_paths.append(d.metadata.get("file_path", "?"))
            j = text_to_idx.get(d.page_content)
            if j is not None:
                dense_idx.append(j)

        bm_hits = bm.top(text, FUSE_DEPTH)
        bm_idx = [i for i, _ in bm_hits]
        fused_idx = rrf([dense_idx, bm_idx])

        rows.append({
            "id": qid, "source": source, "lang": lang, "query": text,
            "gold": sorted(gold),
            "dense": first_hit(dense_paths, gold),
            "bm25": first_hit([paths[i] for i in bm_idx], gold),
            "rrf": first_hit([paths[i] for i in fused_idx], gold),
            "dense_top3": dense_paths[:3],
            "bm25_top3": [paths[i] for i in bm_idx[:3]],
            "rrf_top3": [paths[i] for i in fused_idx[:3]],
        })

    methods = ["dense", "bm25", "rrf"]
    print("=" * 78)
    for lang in ("ko", "en"):
        sub = [r for r in rows if r["lang"] == lang]
        print(f"=== {lang.upper()} ===")
        for m in methods:
            print(row(m, summarize([r[m] for r in sub])))
        print()

    print("=== 전체 (ko+en) ===")
    overall = {m: summarize([r[m] for r in rows]) for m in methods}
    for m in methods:
        print(row(m, overall[m]))

    d, f_ = overall["dense"], overall["rrf"]
    print("\n=== RRF − dense ===")
    for key, label in (("r1", "Recall@1"), ("r3", "Recall@3"), ("r5", f"Recall@{K}")):
        print(f"  {label:<10} {f_[key]-d[key]:+.1%}")
    print(f"  {'MRR':<10} {f_['mrr']-d['mrr']:+.3f}")

    print("\n=== 소스별 (전체) ===")
    by_src = defaultdict(list)
    for r in rows:
        by_src[r["source"]].append(r)
    for src in sorted(by_src):
        print(f"  [{src}]")
        for m in methods:
            print(row("  " + m, summarize([r[m] for r in by_src[src]])))

    changed = [r for r in rows if (r["dense"] is None) != (r["rrf"] is None)
               or (r["dense"] or 99) != (r["rrf"] or 99)]
    if changed:
        print(f"\n=== 순위가 바뀐 질의 {len(changed)}건 ===")
        for r in changed:
            print(f"  [{r['lang']}] {r['id']}  dense={r['dense']} bm25={r['bm25']} rrf={r['rrf']}")
            print(f"        {r['query'][:60]}")
            print(f"        정답 {r['gold']}")
            print(f"        rrf  {r['rrf_top3']}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"k": K, "fuse_depth": FUSE_DEPTH,
                   "overall": overall, "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()

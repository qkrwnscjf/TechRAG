"""
"코드 펜스가 있으면 청크를 800 으로 키운다" 는 휴리스틱을 직접 검증한다.

배경
----
`ingest/chunker.py:35` 는 본문에 ``` 이 있으면 800/50, 없으면 500/50 을 쓴다.
이 규칙에는 측정 근거가 없다. 직관으로 넣었고 검증된 적이 없다.

Phase 23 의 스윕은 800/50 이 측정한 설정 중 가장 나빴다고 기록했지만,
그 스윕은 **균일 크기**로 돌렸다. 즉 "800 이 나쁘다" 는 쟀어도
"코드가 있을 때 800 을 쓰는 규칙" 자체는 잰 적이 없다. 이번에 그것을 잰다.

설정
----
  current    운영 청커를 **그대로 호출**한다. 재구현하면 다른 것을 재게 된다.
  all-500    표준 분할기(500/50)를 전부에 적용 — 휴리스틱 제거
  all-800    코드 분할기(800/50)를 전부에 적용 — 휴리스틱이 항상 켜진 경우

current 와 all-500 의 차이가 **분기 결정 하나**다. 여기서 결론이 난다.
all-800 은 "800 자체가 나쁜가" 를 분리해 보기 위한 참고선이다.

Pinecone 을 쓰지 않는다. 임베딩이 정규화되어 있어 내적이 곧 코사인이므로
numpy 행렬 하나면 충분하고, 운영 색인을 건드릴 위험도 없다.

LLM 호출 0회.

    docker compose exec -d backend-api sh -c "python eval/run_codefence_eval.py > /app/data/cf.log 2>&1"
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.documents import Document                        # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

from ingest.chunker import chunk_documents                           # noqa: E402
from store.vectorstore import get_vector_store_manager               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = "/app/data/codefence_eval.log"
OUT = "/app/data/codefence_eval.json"
BATCH = 64
K = 5

# chunker.py 의 두 분할기를 그대로 옮겼다. 값이 어긋나면 분기 하나가 아니라
# 분할기 설정까지 같이 비교하게 되므로, 변경 시 chunker.py 와 함께 고쳐야 한다.
STANDARD = dict(chunk_size=500, chunk_overlap=50,
                separators=["\n\n", "\n", ".", " ", ""])
CODE = dict(chunk_size=800, chunk_overlap=50,
            separators=["\n\n", "\n", " ", ""])


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def chunk_current(documents):
    """운영 청커를 그대로 호출한다."""
    docs = [Document(page_content=d["text"], metadata={"file_path": d["file_path"]})
            for d in documents]
    out = chunk_documents(docs)
    return [c.page_content for c in out], [c.metadata["file_path"] for c in out]


def chunk_uniform(documents, params):
    splitter = RecursiveCharacterTextSplitter(**params)
    texts, paths = [], []
    for d in documents:
        for piece in splitter.split_text(d["text"]):
            texts.append(piece)
            paths.append(d["file_path"])
    return texts, paths


def embed_all(emb, texts, label):
    vecs, t0 = [], time.perf_counter()
    for i in range(0, len(texts), BATCH):
        vecs.extend(emb.embed_documents(texts[i:i + BATCH]))
        done = min(i + BATCH, len(texts))
        if done % (BATCH * 5) == 0 or done == len(texts):
            rate = done / (time.perf_counter() - t0)
            log(f"    {label}  {done}/{len(texts)}  "
                f"({rate:.1f}청크/s, 남은 {(len(texts)-done)/rate/60:.1f}분)")
    return np.asarray(vecs, dtype=np.float32)


def metrics(ranks):
    n = len(ranks) or 1
    at = lambda m: sum(1 for r in ranks if r and r <= m) / n          # noqa: E731
    return {"n": len(ranks), "r1": at(1), "r3": at(3), "r5": at(K),
            "mrr": sum(1.0 / r for r in ranks if r) / n}


def line(label, s):
    return (f"  {label:<12} n={s['n']:>3}  R@1 {s['r1']:6.1%}  R@3 {s['r3']:6.1%}  "
            f"R@{K} {s['r5']:6.1%}  MRR {s['mrr']:.3f}")


def main():
    with open(os.path.join(HERE, "sweep_corpus.json"), encoding="utf-8") as f:
        corpus = json.load(f)
    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        golden = json.load(f)

    sources = set(corpus["sources"])
    questions = [q for q in golden["questions"] if q["source"] in sources]
    docs = corpus["documents"]

    # 휴리스틱이 실제로 몇 개 문서에 적용되는지. 적용률이 낮으면 애초에 영향이 작다.
    fenced = sum(1 for d in docs if "```" in d["text"])
    log(f"START  {len(docs)}파일 · {sum(len(d['text']) for d in docs):,}자 · "
        f"질문 {len(questions)}개(ko/en) = {len(questions)*2}질의")
    log(f"       코드 펜스 포함 문서 {fenced}/{len(docs)} ({fenced/len(docs):.0%}) "
        f"-> 이 비율만큼 800/50 이 적용된다")

    emb = get_vector_store_manager().embeddings

    queries = [(q["id"], "ko", q["question_ko"], q["source"], set(q["gold_paths"]))
               for q in questions]
    queries += [(q["id"], "en", q["question_en"], q["source"], set(q["gold_paths"]))
                for q in questions]
    qvecs = np.asarray([emb.embed_query(t) for _, _, t, _, _ in queries],
                       dtype=np.float32)
    log(f"질의 {len(queries)}건 임베딩 완료")

    configs = [
        ("current", lambda: chunk_current(docs)),
        ("all-500", lambda: chunk_uniform(docs, STANDARD)),
        ("all-800", lambda: chunk_uniform(docs, CODE)),
    ]

    results = {}
    for label, build in configs:
        texts, paths = build()
        log(f"  [{label}] {len(texts):,}청크 임베딩 시작")
        mat = embed_all(emb, texts, label)
        sims = qvecs @ mat.T                       # 정규화되어 있으므로 내적 = 코사인
        topk = np.argsort(-sims, axis=1)[:, :K]

        rows = []
        for qi, (qid, lang, _, src, gold) in enumerate(queries):
            rank = next((p for p, c in enumerate(topk[qi], 1) if paths[c] in gold), None)
            rows.append({"id": qid, "lang": lang, "source": src, "rank": rank,
                         "top": [paths[c] for c in topk[qi]]})
        results[label] = {"chunks": len(texts), "rows": rows}
        log(f"  [{label}] 완료 {len(texts):,}청크")

    log("=" * 78)
    log("=== 전체 ===")
    for label, r in results.items():
        log(line(label, metrics([x["rank"] for x in r["rows"]])))

    for lang in ("ko", "en"):
        log(f"=== {lang.upper()} ===")
        for label, r in results.items():
            log(line(label, metrics([x["rank"] for x in r["rows"] if x["lang"] == lang])))

    for src in sorted(sources):
        log(f"=== {src} ===")
        for label, r in results.items():
            log(line(label, metrics([x["rank"] for x in r["rows"] if x["source"] == src])))

    log("=== 청크 수 (저장·적재 비용) ===")
    for label, r in results.items():
        log(f"  {label:<12} {r['chunks']:,}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"k": K, "fenced_docs": fenced, "total_docs": len(docs),
                   "results": results}, f, ensure_ascii=False, indent=2)
    log(f"DONE  {OUT}")


if __name__ == "__main__":
    main()

"""
청크 전략 스윕. 설정마다 부분 코퍼스를 다시 잘라 임베딩하고 검색 품질을 잰다.

Pinecone 을 쓰지 않는다. 설정별로 인덱스를 새로 만들어야 하는데 운영 색인에 넣었다
지우기를 반복하면 (1) 적재 비용이 들고 (2) 도중에 죽으면 운영 색인이 오염된다.
임베딩은 정규화되어 있으므로(normalize_embeddings=True) 내적이 곧 코사인 유사도다.
numpy 행렬 하나면 충분하다.

정답은 골든셋의 file_path 로 정의된다. 청크 경계가 바뀌어도 정답 정의가 그대로라
설정 간 비교가 성립한다. 이것이 정답을 문자열 포함이 아니라 파일 경로로 잡은 이유다.

LLM 호출 0회.

    docker compose exec -d backend-api python eval/run_sweep.py
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402
from store.vectorstore import get_vector_store_manager  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = "/app/data/sweep.log"
OUT = "/app/data/sweep_results.json"
BATCH = 64

CONFIGS = [
    (256, 50),
    (512, 50),
    (512, 128),
    (800, 50),
    (1024, 128),
]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def chunk_corpus(documents, size, overlap):
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap)
    texts, paths = [], []
    for d in documents:
        for piece in splitter.split_text(d["text"]):
            texts.append(piece)
            paths.append(d["file_path"])
    return texts, paths


def embed_all(emb, texts, label):
    vecs = []
    t0 = time.perf_counter()
    for i in range(0, len(texts), BATCH):
        vecs.extend(emb.embed_documents(texts[i:i + BATCH]))
        done = min(i + BATCH, len(texts))
        if done % (BATCH * 5) == 0 or done == len(texts):
            rate = done / (time.perf_counter() - t0)
            eta = (len(texts) - done) / rate if rate else 0
            log(f"    {label}  {done}/{len(texts)}  ({rate:.1f}청크/s, 남은 {eta/60:.1f}분)")
    return np.asarray(vecs, dtype=np.float32), time.perf_counter() - t0


def metrics(ranks, k):
    n = len(ranks)
    at = lambda m: sum(1 for r in ranks if r and r <= m) / n          # noqa: E731
    return {
        "n": n,
        "recall@1": at(1), "recall@3": at(3), f"recall@{k}": at(k),
        "mrr": sum(1.0 / r for r in ranks if r) / n,
    }


def main():
    with open(os.path.join(HERE, "sweep_corpus.json"), encoding="utf-8") as f:
        corpus = json.load(f)
    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        golden = json.load(f)

    sources = set(corpus["sources"])
    questions = [q for q in golden["questions"] if q["source"] in sources]
    docs = corpus["documents"]
    k = 5

    log(f"START  코퍼스 {len(docs)}파일 · {sum(len(d['text']) for d in docs):,}자 "
        f"· 질문 {len(questions)}개(ko/en) · 설정 {len(CONFIGS)}개")

    emb = get_vector_store_manager().embeddings

    # 질의 임베딩은 설정과 무관하므로 한 번만 계산해 재사용한다.
    queries = [(q["id"], "ko", q["question_ko"], set(q["gold_paths"])) for q in questions]
    queries += [(q["id"], "en", q["question_en"], set(q["gold_paths"])) for q in questions]
    qvecs = np.asarray([emb.embed_query(t) for _, _, t, _ in queries], dtype=np.float32)
    log(f"질의 {len(queries)}건 임베딩 완료")

    results = []
    for size, overlap in CONFIGS:
        label = f"{size}/{overlap}"
        texts, paths = chunk_corpus(docs, size, overlap)
        log(f"  [{label}] {len(texts):,}청크 임베딩 시작")
        mat, secs = embed_all(emb, texts, label)

        # 정규화된 벡터이므로 내적 = 코사인
        sims = qvecs @ mat.T                       # (질의, 청크)
        topk = np.argsort(-sims, axis=1)[:, :k]

        rows = []
        for qi, (qid, lang, _, gold) in enumerate(queries):
            rank = None
            for pos, ci in enumerate(topk[qi], start=1):
                if paths[ci] in gold:
                    rank = pos
                    break
            rows.append({"id": qid, "lang": lang, "rank": rank,
                         "top": [paths[c] for c in topk[qi]]})

        entry = {
            "config": label, "chunk_size": size, "overlap": overlap,
            "chunks": len(texts), "embed_seconds": round(secs, 1),
            "all": metrics([r["rank"] for r in rows], k),
            "ko": metrics([r["rank"] for r in rows if r["lang"] == "ko"], k),
            "en": metrics([r["rank"] for r in rows if r["lang"] == "en"], k),
            "rows": rows,
        }
        results.append(entry)
        a = entry["all"]
        log(f"  [{label}] 완료 {len(texts):,}청크 {secs/60:.1f}분  "
            f"R@1 {a['recall@1']:.1%}  R@3 {a['recall@3']:.1%}  "
            f"R@{k} {a[f'recall@{k}']:.1%}  MRR {a['mrr']:.3f}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"k": k, "corpus": corpus["report"], "results": results},
                  f, ensure_ascii=False, indent=2)

    log("=" * 78)
    log(f"{'설정':<10} {'청크':>7} {'R@1':>7} {'R@3':>7} {'R@5':>7} {'MRR':>7} {'임베딩':>7}")
    for e in results:
        a = e["all"]
        log(f"{e['config']:<10} {e['chunks']:>7,} {a['recall@1']:>7.1%} "
            f"{a['recall@3']:>7.1%} {a[f'recall@{k}']:>7.1%} {a['mrr']:>7.3f} "
            f"{e['embed_seconds']/60:>6.1f}분")
    log(f"DONE   결과 저장: {OUT}")


if __name__ == "__main__":
    main()

"""
실제 색인(Pinecone)에서 파일 단위와 **청크 단위** 검색 품질을 함께 잰다.

Phase 28 에서 드러난 것:

    골든셋의 정답 정의는 file_path 다. 그래서 "정답 문서의 답이 없는 조각" 이 와도
    지표상 성공으로 집계된다. 실제 실패는 여기서 났다.

그래서 두 가지를 나눠 본다.

  file_rank    정답 문서의 청크가 몇 위에 있는가        (기존 지표)
  answer_rank  그중 **답을 담은** 청크가 몇 위에 있는가  (이번에 필요한 지표)

answer_rank 의 정답은 키워드로 근사한다. 사람이 청크마다 라벨링한 것이 아니므로
**대리 지표임을 명시한다.** 헤딩 접두어에 들어간 단어가 거짓 양성을 만들지 않도록
키워드는 접두어를 뗀 본문에서만 찾는다.

LLM 호출 0회.

    docker compose exec -T backend-api python eval/run_chunk_level_eval.py --tag before
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.vectorstore import get_vector_store_manager        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
K = 5
SOURCE = "vllm"

# 골든셋에 없는 "일반적인" 질문. 골든셋 질문은 본문 어휘(qk_max 등)를 그대로 쓰기
# 때문에 Phase 28 의 실패가 재현되지 않는다.
GENERAL = [
    {"id": "gen-01", "gold_file": "docs/design/paged_attention.md",
     "ko": "vLLM 의 PagedAttention 은 어떻게 동작하나요?",
     "en": "How does PagedAttention work in vLLM?"},
    {"id": "gen-02", "gold_file": "docs/design/paged_attention.md",
     "ko": "vLLM 은 key 와 value 데이터를 메모리에 어떻게 저장하나요?",
     "en": "How does vLLM store key and value data in memory?"},
    {"id": "gen-03", "gold_file": "docs/design/paged_attention.md",
     "ko": "어텐션 커널에서 softmax 는 어떻게 계산되나요?",
     "en": "How is softmax computed in the attention kernel?"},
]
# 답 조각 판정 표식은 answer_keys.json 에서 읽는다.
# 직접 하드코딩했다가 실패한 적이 있다. "thread block" 을 표식에 넣었는데
# 경고문 조각이 용어를 정의하며 그 표현을 써서, 실패 사례를 성공으로 셌다.
# 지금은 비정답 조각에 표식이 없는지 실행 때마다 검증한다.
with open(os.path.join(HERE, "answer_keys.json"), encoding="utf-8") as _f:
    ANSWER_KEYS_SPEC = json.load(_f)
_PREFIX = re.compile(r"^\[[^\]]{0,120}\]\s*")


def markers_for(qid):
    return ANSWER_KEYS_SPEC["questions"][qid]["answer_markers"]


def summarize(ranks):
    n = len(ranks) or 1
    at = lambda m: sum(1 for r in ranks if r and r <= m) / n      # noqa: E731
    return {"n": len(ranks), "r1": at(1), "r3": at(3), "r5": at(K),
            "mrr": sum(1.0 / r for r in ranks if r) / n}


def line(label, s):
    return (f"  {label:<24} n={s['n']:>3}  @1 {s['r1']:6.1%}  @3 {s['r3']:6.1%}  "
            f"@{K} {s['r5']:6.1%}  MRR {s['mrr']:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="before / after 등 실행 구분")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or f"/app/data/chunk_level_{args.tag}.json"

    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        golden = [q for q in json.load(f)["questions"] if q["source"] == SOURCE]

    retriever = get_vector_store_manager().as_retriever(k=K)

    queries = []
    for q in golden:
        for lang in ("ko", "en"):
            queries.append((q["id"], lang, q[f"question_{lang}"], set(q["gold_paths"]), False))
    for g in GENERAL:
        for lang in ("ko", "en"):
            queries.append((g["id"], lang, g[lang], {g["gold_file"]}, True))

    print(f"[{args.tag}] 질의 {len(queries)}건 · 실제 색인 조회 · LLM 0회\n")

    rows = []
    for qid, lang, text, gold, general in queries:
        docs = retriever.invoke(text)
        file_rank, answer_rank = None, None
        for i, d in enumerate(docs, start=1):
            if d.metadata.get("file_path") not in gold:
                continue
            if file_rank is None:
                file_rank = i
            if not general:
                continue
            # 접두어에 들어간 헤딩 단어가 거짓 양성을 만들지 않도록 본문에서만 찾는다
            body = _PREFIX.sub("", d.page_content)
            if answer_rank is None and any(m.lower() in body.lower() for m in markers_for(qid)):
                answer_rank = i
        rows.append({"id": qid, "lang": lang, "general": general, "query": text,
                     "gold": sorted(gold), "file_rank": file_rank, "answer_rank": answer_rank,
                     "top": [d.metadata.get("file_path", "?") for d in docs]})

    gold_rows = [r for r in rows if not r["general"]]
    gen_rows = [r for r in rows if r["general"]]

    print("=== 골든셋 (vLLM) · 파일 단위 ===")
    print(line("file_rank", summarize([r["file_rank"] for r in gold_rows])))
    print("\n=== 일반 질문 · 파일 단위 ===")
    print(line("file_rank", summarize([r["file_rank"] for r in gen_rows])))
    print("\n=== 일반 질문 · 정답 청크 단위 (표적) ===")
    print(line("answer_rank", summarize([r["answer_rank"] for r in gen_rows])))

    print("\n=== 일반 질문별 상세 ===")
    for r in gen_rows:
        print(f"  {r['id']} {r['lang']}  파일={r['file_rank']}  답청크={r['answer_rank']}")
        print(f"      {r['top'][:3]}")

    with open(out, "w", encoding="utf-8") as f:
        json.dump({"tag": args.tag, "k": K,
                   "answer_keys": ANSWER_KEYS_SPEC["questions"],
                   "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()

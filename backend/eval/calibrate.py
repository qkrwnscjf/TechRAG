"""
임베딩 처리량을 실측한다. 스윕 규모를 추정으로 정하지 않기 위한 사전 단계다.

오늘 소요 시간 추정이 두 번 크게 빗나갔다(23분 -> 76분). 원인은 다른 조건에서 잰
수치를 그대로 가져다 쓴 것이었다. 그래서 이번에는 스윕에 쓸 바로 그 조건
(같은 컨테이너, 같은 모델, 같은 배치 크기)에서 직접 재고 그 값으로만 계산한다.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402
from store.vectorstore import get_vector_store_manager  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIGS = [(256, 50), (512, 50), (512, 128), (800, 50), (1024, 128)]


def main():
    with open(os.path.join(HERE, "sweep_corpus.json"), encoding="utf-8") as f:
        corpus = json.load(f)
    docs = corpus["documents"]
    total_chars = sum(len(d["text"]) for d in docs)
    print(f"코퍼스 {len(docs)}파일 · {total_chars:,}자\n")

    print("설정별 청크 수 (임베딩 없이 분할만)")
    counts = {}
    for size, overlap in CONFIGS:
        sp = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap)
        n = sum(len(sp.split_text(d["text"])) for d in docs)
        counts[(size, overlap)] = n
        print(f"  {size:>4}/{overlap:<4}  {n:>6,} 청크")
    grand = sum(counts.values())
    print(f"  {'합계':>9}  {grand:>6,} 청크\n")

    # 실제 스윕과 같은 조건에서 임베딩 속도를 잰다
    sp = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=50)
    texts = []
    for d in docs:
        texts += sp.split_text(d["text"])
    sample = texts[:64]

    emb = get_vector_store_manager().embeddings
    emb.embed_documents(sample[:8])          # 워밍업 (첫 호출은 초기화 비용이 섞인다)

    t0 = time.perf_counter()
    vecs = emb.embed_documents(sample)
    elapsed = time.perf_counter() - t0

    per_chunk = elapsed / len(sample)
    print(f"임베딩 실측  {len(sample)}청크 / {elapsed:.1f}초  ->  청크당 {per_chunk*1000:.0f}ms")
    print(f"차원 {len(vecs[0])}\n")

    print("실측값 기준 스윕 소요 추정")
    for (size, overlap), n in counts.items():
        print(f"  {size:>4}/{overlap:<4}  {n:>6,}청크  {n*per_chunk/60:>6.1f}분")
    print(f"  {'전체':>9}  {grand:>6,}청크  {grand*per_chunk/60:>6.1f}분")


if __name__ == "__main__":
    main()

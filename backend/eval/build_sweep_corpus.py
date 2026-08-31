"""
청크 스윕용 부분 코퍼스를 만든다.

전체 코퍼스(7,712청크)로 스윕하면 설정 하나당 재색인이 필요해 현실적이지 않다.
(실측 730ms/청크 기준 설정 5개면 78분) 대신 대표성 있는 부분집합을 만든다.

선별 기준은 셋이다.
  1) 골든셋 정답 문서              — 없으면 측정 자체가 불가능
  2) 베이스라인에서 관측된 방해 문서 — 없으면 실패 사례가 사라져 스윕이 무의미해진다
     (Prefect 개념 문서가 예제·how-to 문서에 밀리는 것이 핵심 관찰이었다)
  3) 무작위 보충                   — 현실적인 혼동을 유지. 시드 고정으로 재현 가능

기본 대상은 Prefect 하나다. 베이스라인에서 vLLM·Langfuse 는 R@5 100% 라
청크 설정을 바꿔도 움직일 여지가 없다. 개선 여지가 있는 곳만 측정한다.

레포는 한 번만 클론하고 결과를 JSON 으로 저장한다. 이후 스윕은 이 파일만 읽는다.
"""
import argparse
import json
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.loader import _shallow_clone  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20260831
EXTS = (".md", ".mdx")

REPOS = {
    "vllm": "https://github.com/vllm-project/vllm",
    "prefect": "https://github.com/PrefectHQ/prefect",
    "langfuse": "https://github.com/langfuse/langfuse-docs",
}

# 베이스라인(eval_baseline.json)에서 정답을 밀어낸 문서들.
# 스윕에서 이들이 빠지면 "개념 문서가 예제에 밀린다"는 현상 자체가 재현되지 않는다.
DISTRACTORS = {
    "prefect": [
        "docs/v3/how-to-guides/migrate/upgrade-to-prefect-3.mdx",
        "docs/v3/examples/run-api-sourced-etl.mdx",
        "docs/v3/examples/run-dbt-with-prefect.mdx",
        "docs/v3/how-to-guides/workflows/write-and-run.mdx",
        "docs/v3/how-to-guides/workflows/assets.mdx",
        "docs/v3/get-started/quickstart.mdx",
        "docs/v3/concepts/artifacts.mdx",
        "docs/v3/examples/hello-world.mdx",
        "README.md",
    ],
}


def collect(repo_dir):
    """레포에서 대상 확장자 파일을 (상대경로 -> 본문) 으로 모은다."""
    out = {}
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            if not fn.lower().endswith(EXTS):
                continue
            full = os.path.join(root, fn)
            try:
                text = open(full, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            if text.strip():
                out[os.path.relpath(full, repo_dir)] = text
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="+", default=["prefect"], choices=list(REPOS))
    ap.add_argument("--char-budget", type=int, default=320_000)
    ap.add_argument("--max-fill-chars", type=int, default=12_000,
                    help="무작위 보충 파일 하나의 상한. 큰 파일이 예산을 독점하지 않게 한다")
    ap.add_argument("--out", default=os.path.join(HERE, "sweep_corpus.json"))
    args = ap.parse_args()

    with open(os.path.join(HERE, "golden_set.json"), encoding="utf-8") as f:
        golden = json.load(f)

    gold_by_source = {}
    for q in golden["questions"]:
        gold_by_source.setdefault(q["source"], set()).update(q["gold_paths"])

    rng = random.Random(SEED)
    corpus, report = [], []
    budget_each = args.char_budget // len(args.sources)

    for source in args.sources:
        tmp = tempfile.mkdtemp()
        try:
            _, branch = _shallow_clone(REPOS[source], tmp)
            files = collect(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        gold = sorted(gold_by_source.get(source, set()))
        missing = [p for p in gold if p not in files]
        if missing:
            print(f"  !! {source}: 정답 문서를 레포에서 찾지 못했습니다 -> {missing}")

        picked = [p for p in gold if p in files]
        n_gold = len(picked)
        picked += [p for p in DISTRACTORS.get(source, []) if p in files and p not in picked]
        n_dist = len(picked) - n_gold

        chars = sum(len(files[p]) for p in picked)
        pool = [p for p in sorted(set(files) - set(picked))
                if len(files[p]) <= args.max_fill_chars]
        rng.shuffle(pool)
        for p in pool:
            if chars >= budget_each:
                break
            picked.append(p)
            chars += len(files[p])
        n_fill = len(picked) - n_gold - n_dist

        for p in picked:
            corpus.append({"source": source, "file_path": p, "text": files[p]})

        report.append({"source": source, "branch": branch, "repo_files": len(files),
                       "picked": len(picked), "chars": chars,
                       "gold": n_gold, "distractors": n_dist, "fill": n_fill})
        print(f"  {source:<9} 브랜치 {branch:<8} 레포 {len(files):>4}파일 -> "
              f"선별 {len(picked):>3}파일 ({chars:,}자)")
        print(f"            정답 {n_gold} · 방해 {n_dist} · 보충 {n_fill}  "
              f"(정답 비율 {n_gold/len(picked):.0%})")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"seed": SEED, "sources": args.sources,
                   "char_budget": args.char_budget,
                   "report": report, "documents": corpus}, f, ensure_ascii=False)

    total = sum(len(d["text"]) for d in corpus)
    print(f"\n총 {len(corpus)}파일 · {total:,}자")
    print(f"저장: {args.out}  ({os.path.getsize(args.out)/1e6:.1f}MB)")


if __name__ == "__main__":
    main()

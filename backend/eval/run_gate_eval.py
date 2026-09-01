"""
contextualize 규칙 게이트 평가.

두 가지를 잰다.

1) 분류 정확도 (LLM 0회)
   게이트가 "문맥이 필요한 질문" 을 놓치지 않는가.
   거짓 음성(필요한데 건너뜀)은 답을 무너뜨리므로 위험하고,
   거짓 양성(불필요한 호출)은 비용만 든다. 둘을 나눠 본다.

2) 건너뛴 호출이 실제로 낭비였는가 (LLM 소량)
   게이트가 건너뛰기로 한 질문에 실제 contextualize 를 돌려 본다.
   LLM 이 질문을 그대로 돌려준다면 그 호출은 애초에 낭비였다는 뜻이다.
   --verify 를 줄 때만 실행한다.

    docker compose exec -T backend-api python eval/run_gate_eval.py
    docker compose exec -T backend-api python eval/run_gate_eval.py --verify
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.nodes import needs_context                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def normalize(s):
    return " ".join(str(s).split()).strip().rstrip("?.!").lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="건너뛴 질문에 실제 contextualize 를 돌려 낭비였는지 확인 (LLM 호출 발생)")
    ap.add_argument("--out", default="/app/data/gate_eval.json")
    args = ap.parse_args()

    with open(os.path.join(HERE, "followups.json"), encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    rows = []
    for c in cases:
        pred = needs_context(c["question"])
        rows.append({**c, "predicted": pred, "correct": pred == c["needs_context"]})

    tp = sum(1 for r in rows if r["needs_context"] and r["predicted"])
    fn = sum(1 for r in rows if r["needs_context"] and not r["predicted"])
    tn = sum(1 for r in rows if not r["needs_context"] and not r["predicted"])
    fp = sum(1 for r in rows if not r["needs_context"] and r["predicted"])
    n = len(rows)

    print(f"=== 게이트 분류 (n={n}) ===")
    print(f"  정확도            {(tp+tn)/n:6.1%}")
    print(f"  재현율(위험 회피)  {tp/(tp+fn):6.1%}   문맥 필요 {tp+fn}건 중 {tp}건 포착")
    print(f"  거짓 음성 (위험)   {fn}건   ← 문맥이 필요한데 건너뜀")
    print(f"  거짓 양성 (낭비)   {fp}건   ← 불필요한 LLM 호출")

    skipped = [r for r in rows if not r["predicted"]]
    print(f"\n=== 호출 절감 ===")
    print(f"  후속 질문 {n}건 중 건너뜀 {len(skipped)}건  ->  LLM 호출 {len(skipped)/n:.0%} 절감")

    if fn:
        print("\n=== 거짓 음성 (건너뛰면 안 되는데 건너뜀) ===")
        for r in rows:
            if r["needs_context"] and not r["predicted"]:
                print(f"  {r['id']}  {r['question']!r}")
    if fp:
        print("\n=== 거짓 양성 (불필요하게 호출) ===")
        for r in rows:
            if not r["needs_context"] and r["predicted"]:
                print(f"  {r['id']}  {r['question']!r}")

    verified = None
    if args.verify:
        from langchain_core.output_parsers import StrOutputParser
        from agent.prompts import contextualize_prompt
        from agent.nodes import llm

        targets = [r for r in rows if not r["predicted"]]
        print(f"\n=== 건너뛴 {len(targets)}건에 실제 contextualize 실행 (LLM {len(targets)}회) ===")
        chain = contextualize_prompt | llm | StrOutputParser()
        unchanged = 0
        verified = []
        for r in targets:
            history = f"User: {r['prior']}"
            out = chain.invoke({"chat_history": history, "question": r["question"]})
            same = normalize(out) == normalize(r["question"])
            unchanged += same
            verified.append({"id": r["id"], "question": r["question"],
                             "llm_output": out.strip(), "unchanged": same})
            print(f"  {r['id']}  {'그대로' if same else '변경됨'}")
            if not same:
                print(f"        입력: {r['question']}")
                print(f"        출력: {out.strip()[:100]}")
        print(f"\n  {unchanged}/{len(targets)} 건이 입력과 동일 "
              f"-> 그 호출들은 낭비였다 ({unchanged/len(targets):.0%})")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"n": n, "tp": tp, "fn": fn, "tn": tn, "fp": fp,
                   "skip_rate": len(skipped) / n, "rows": rows,
                   "verified": verified}, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {args.out}")


if __name__ == "__main__":
    main()

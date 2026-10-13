import json
from .copilot import ask
from .pipeline import save_json


def evaluate(root, report):
    cases = json.loads((root / "docs/eval_cases.json").read_text())
    rows = []
    for case in cases:
        result = ask(report, case["question"])
        supported = case["intent"] != "unsupported"
        rows.append({**case, "actual_intent": result["intent"], "status": result["status"],
            "intent_correct": case["intent"] == result["intent"],
            "behavior_correct": (result["status"] == "answered") == supported,
            "source_present": case["source"] in result["evidence_ids"] if case["source"] else None,
            "evidence_ids": result["evidence_ids"], "elapsed_ms": result["elapsed_ms"]})
    source_rows = [r for r in rows if r["source"]]
    summary = {"mode": "offline_evidence_template", "cases": len(rows),
        "intent_accuracy": sum(r["intent_correct"] for r in rows) / len(rows),
        "answer_or_abstain_accuracy": sum(r["behavior_correct"] for r in rows) / len(rows),
        "required_source_hit_rate": sum(r["source_present"] for r in source_rows) / len(source_rows),
        "source_cases": len(source_rows), "live_llm_evaluated": False,
        "limitations": "Small author-written development set; not a blind benchmark or semantic LLM factuality evaluation.",
        "results": rows}
    save_json(root / "artifacts/copilot_evaluation.json", summary)
    return summary

import argparse
import json
from pathlib import Path
from .pipeline import build
from .copilot import ask
from .evaluate import evaluate
from .server import serve

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="PortfolioLens AI: synthetic financial analytics and bounded AI")
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build")
    b.add_argument("--loans", type=int, default=4000)
    b.add_argument("--seed", type=int, default=42)
    s = commands.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    q = commands.add_parser("ask")
    q.add_argument("question")
    q.add_argument("--mode", choices=["offline", "openai"], default="offline")
    commands.add_parser("evaluate")
    args = parser.parse_args()
    try:
        if args.command == "build":
            report = build(ROOT, args.loans, args.seed)
            ev = evaluate(ROOT, report)
            print(json.dumps({"as_of": report["as_of"], "quality": report["quality"],
                "model": report["model"]["selected_model"], "test": report["model"]["test"],
                "copilot": {k:v for k,v in ev.items() if k != "results"}}, indent=2))
        elif args.command == "serve":
            serve(ROOT, args.port)
        else:
            report = json.loads((ROOT / "artifacts/dashboard.json").read_text())
            result = evaluate(ROOT, report) if args.command == "evaluate" else ask(
                report, args.question, args.mode, ROOT / "artifacts/copilot_audit.jsonl")
            print(json.dumps(result, indent=2))
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()

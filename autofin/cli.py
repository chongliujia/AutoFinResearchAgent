from __future__ import annotations

import argparse
import json

from autofin.runtime import ResearchOrchestrator, SkillRegistry
from autofin.schemas import ResearchTask
from autofin.skills import SecFilingAnalysisSkill


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autofin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a financial research skill")
    run_parser.add_argument("skill_name")
    run_parser.add_argument("--ticker", required=True)
    run_parser.add_argument("--filing-type", default="10-K")
    run_parser.add_argument(
        "--objective",
        default="Analyze SEC filing",
        help="Natural language objective used by the orchestrator.",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the local web UI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8097)
    serve_parser.add_argument("--reload", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run":
        registry = SkillRegistry([SecFilingAnalysisSkill()])
        orchestrator = ResearchOrchestrator(registry)
        task = ResearchTask(
            objective=args.objective,
            skill_name=args.skill_name,
            inputs={"ticker": args.ticker, "filing_type": args.filing_type},
        )
        result = orchestrator.run(task)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "autofin.web.app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )


if __name__ == "__main__":
    main()

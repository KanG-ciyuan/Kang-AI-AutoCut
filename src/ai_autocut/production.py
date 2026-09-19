"""One launch: source folder + brief -> as far as the machine can legitimately go.

    python3 -m src.ai_autocut.production run \\
        --source <source folder> \\
        --brief <brief.json> \\
        --workspace <workspace> \\
        [--agent-command "<command>"] \\
        [--until "<stage name>"]

Before this module existed the answer to "start a SKU" was a sequence of hand-run G1A,
G1B, G1C ... steps, because the fast path could only tell you which artifact was missing.
This initialises the job, then hands the chain to the orchestrator, which authors what the
machine is entitled to author and stops only where a decision is genuinely required.

Exit codes follow the repository's existing convention:

    0  completed
    3  blocked by a real environment/engineering problem
    5  stopped at a gate that needs a Producer decision
    6  failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import authoring, job_foundation, production_orchestrator

EXIT_COMPLETE = 0
EXIT_BLOCKED = 3
EXIT_GATE = 5
EXIT_FAILED = 6

#: Fields a brief must state. Everything else has a documented default, because a brief
#: exists to remove setup friction, not to become another schema to satisfy.
REQUIRED_BRIEF_FIELDS = ("job_id", "product")


class BriefError(ValueError):
    """Raised when a brief cannot be used to start a job."""


def load_brief(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise BriefError(f"brief does not exist: {target}")
    try:
        brief = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BriefError(f"cannot read brief {target}: {exc}") from exc
    if not isinstance(brief, Mapping):
        raise BriefError("a brief must be a JSON object")
    for field in REQUIRED_BRIEF_FIELDS:
        if field not in brief:
            raise BriefError(f"a brief must state {field!r}")
    product = brief["product"]
    if not isinstance(product, Mapping) or not product.get("name"):
        raise BriefError("brief.product must state a 'name'")
    return dict(brief)


def product_descriptor(brief: Mapping[str, Any]) -> dict[str, Any]:
    """Map a brief onto the product identity ``job_foundation`` expects."""

    product = dict(brief["product"])
    return {
        "name": str(product["name"]),
        "name_localized": product.get("name_localized"),
        "market": brief.get("market"),
        "platform": brief.get("platform"),
        "language": brief.get("language"),
        "cta": brief.get("cta"),
        "target_duration_seconds": brief.get("target_duration_seconds"),
        "notes": brief.get("notes"),
    }


def ensure_job(*, brief: Mapping[str, Any], source: Path, workspace: Path) -> Path:
    """Initialize the job once. Re-running must not re-initialise or overwrite."""

    job_root = Path(workspace) / str(brief["job_id"])
    if (job_root / "source_inventory.json").is_file():
        return job_root
    # job_foundation treats `workspace` as the job root itself and refuses to overwrite an
    # existing one, which is exactly the evidence-protection behaviour a re-launch needs.
    job_foundation.initialize_job(
        job_id=str(brief["job_id"]),
        product=product_descriptor(brief),
        source_root=Path(source),
        workspace=job_root,
    )
    return job_root


def run_once(
    *,
    source: Path,
    brief: Mapping[str, Any],
    workspace: Path,
    agent_command: str | None = None,
    until: str | None = None,
    fps: int = 30,
) -> production_orchestrator.ProductionReport:
    job_root = ensure_job(brief=brief, source=Path(source), workspace=Path(workspace))
    agent = (authoring.CommandAuthoringAgent(agent_command) if agent_command
             else authoring.NullAuthoringAgent())
    orchestrator = production_orchestrator.ProductionOrchestrator(
        job_root, job_id=str(brief["job_id"]), fps=fps, agent=agent)
    report = orchestrator.run(until=until)
    evidence = job_root / "recon" / "production_run.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m src.ai_autocut.production",
        description="Run one SKU from a source folder and a brief.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="initialise the job and drive the production chain")
    run.add_argument("--source", type=Path, required=True, help="folder of source media")
    run.add_argument("--brief", type=Path, required=True, help="brief JSON")
    run.add_argument("--workspace", type=Path, required=True, help="workspace root")
    run.add_argument("--agent-command", default=None,
                     help="command invoked once per artifact needing authoring; the "
                          "authoring request arrives on stdin as JSON")
    run.add_argument("--until", default=None,
                     help="stop after this stage completes instead of running on")
    run.add_argument("--fps", type=int, default=30)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "run":
        _parser().error("unknown command")
        return EXIT_FAILED

    try:
        brief = load_brief(args.brief)
        report = run_once(source=args.source, brief=brief, workspace=args.workspace,
                          agent_command=args.agent_command, until=args.until, fps=args.fps)
    except (BriefError, job_foundation.JobFoundationError,
            production_orchestrator.ProductionError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return EXIT_BLOCKED

    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    print(report.explain(), file=sys.stderr)
    if report.stop == production_orchestrator.STOP_COMPLETE:
        return EXIT_COMPLETE
    if report.stop == production_orchestrator.STOP_GATE:
        return EXIT_GATE
    return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())

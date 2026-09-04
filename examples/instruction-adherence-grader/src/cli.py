"""Single CLI entrypoint. (Lane D)

PHASE 0 STUB, but a *runnable* one by design: the Makefile routes every
not-yet-implemented target through this CLI, and the Phase 0 gate requires every
Make target to exit 0. So each subcommand here prints a clear "not implemented yet
(lane X)" message and exits 0. Lane D replaces this file with the real argparse CLI
that wires subcommands to their owning modules; at that point NotImplementedError
from a still-stubbed module is allowed to surface (see docs/AGENT_LANES.md Lane D).
"""

from __future__ import annotations

import argparse
import sys

# subcommand -> owning lane, for the placeholder message.
_SUBCOMMANDS = {
    "fixtures": "lane C",
    "label": "lane C",
    "review": "lane C",
    "grade": "integration",
    "score": "lane D",
    "report": "lane E",
    "demo": "lane D",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grader",
        description="Instruction adherence grader (Phase 0 stub CLI).",
    )
    sub = parser.add_subparsers(dest="command")
    for name in _SUBCOMMANDS:
        p = sub.add_parser(name, help=f"{name} ({_SUBCOMMANDS[name]})")
        p.add_argument("--limit", type=int, default=None, help="limit N for cheap iteration")
        p.add_argument("--no-cache", action="store_true", help="bypass the model call cache")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    lane = _SUBCOMMANDS.get(args.command, "a later lane")
    print(f"{args.command}: not implemented yet ({lane}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

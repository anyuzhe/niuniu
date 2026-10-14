#!/usr/bin/env python3
"""Write read-only run cards (JSON + Markdown) for saved experiments; never touches the artifact folders.

    python scripts/research/run_card.py artifacts/<run_id> [more ...] --out artifacts/_run_cards
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from quantlab.experiments.run_card import write_run_card  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("artifacts", nargs="+", help="experiment folders (or experiment.json files)")
    parser.add_argument("--out", required=True, help="parent folder; one subfolder per run_id is created")
    args = parser.parse_args()
    failed = 0
    for item in args.artifacts:
        path = Path(item)
        path = path / "experiment.json" if path.is_dir() else path
        try:
            import json
            run_id = json.loads(path.read_text()).get("run_id") or path.parent.name
            card = write_run_card(path, Path(args.out) / str(run_id))
            print(f"{run_id}  {card['identity']['kind']:<12} flags={[f['code'] for f in card['flags']]}")
        except (OSError, ValueError) as error:
            failed += 1
            print(f"FAILED {item}: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

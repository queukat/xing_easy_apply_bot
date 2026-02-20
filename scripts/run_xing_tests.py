from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

SCENARIOS = {
    "unit": ["-q", "tests/unit"],
    "integration": ["-q", "-m", "integration", "tests/integration"],
    "e2e": ["-q", "-m", "e2e", "tests/e2e"],
    "all": ["-q", "tests"],
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run XING test scenarios locally")
    parser.add_argument(
        "--scenario",
        choices=tuple(SCENARIOS.keys()),
        default="all",
        help="Which scenario to run.",
    )
    parser.add_argument(
        "--enable-e2e",
        action="store_true",
        help="Enable local execution of e2e tests when scenario=e2e.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    scenario = args.scenario

    if importlib.util.find_spec("pytest") is None:
        print("[xing-test-runner] Module pytest is not installed in this interpreter.")
        print("Run: poetry install  (or: pip install pytest) in the same .venv and retry.")
        return 1

    if scenario == "e2e" and not args.enable_e2e:
        print("[xing-test-runner] e2e disabled by default.")
        print("Set --enable-e2e or XING_E2E_ENABLED=1 for manual e2e runs.")
        return 0

    if args.enable_e2e:
        os.environ.setdefault("XING_E2E_ENABLED", "1")

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))

    cmd = [sys.executable, "-m", "pytest", *SCENARIOS[scenario]]
    result = subprocess.run(cmd, cwd=repo_root)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

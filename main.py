from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    # Позволяет запускать "python main.py collect" без установки пакета.
    root = Path(__file__).resolve().parent
    src_dir = root / "src"
    if src_dir.exists():
        sys.path.insert(0, str(src_dir))

    from xingbot.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()

"""pluz.py -- run any PLUZ5-Cust command:  python pluz.py <command> [args]
Commands: check fetch update validate cleanup dedupe ghclean debug"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
from pluz_cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

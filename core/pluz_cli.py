"""
__main__.py -- entry point (called by pluz.py).

Pure stdlib dispatcher. No network access, no third-party imports. Maps a
subcommand name to the matching pluz_<name> module's main(argv) function.
"""
from __future__ import annotations

import sys

COMMANDS = {
    "check": "pluz_check",
    "fetch": "pluz_fetch",
    "update": "pluz_update",
    "cleanup": "pluz_cleanup",
    "validate": "pluz_validate",
    "dedupe": "pluz_dedupe",
    "ghclean": "pluz_ghclean",
    "debug": "pluz_debug",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("PLUZ5-Cust -- usage: python pluz.py <command> [args]")
        print("")
        print("Commands:")
        for name in COMMANDS:
            print(f"  {name}")
        print("")
        print("Run 'python pluz.py <command> --help' for a command's own options.")
        return 0

    command = sys.argv[1]
    if command not in COMMANDS:
        print(f"[ERROR] unknown command '{command}'. Run with --help to see the list.", file=sys.stderr)
        return 1

    module = __import__(COMMANDS[command])
    return module.main(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from runtime.provision import (
    Provisioner,
    format_command_error,
    require_production_root,
    require_supported_interpreter,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--reexecuted", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        require_production_root(root)
        require_supported_interpreter(root)
        before = git(root, "rev-parse", "HEAD")
        after = before
        if args.dry_run:
            print("Dry run: git pull is not executed")
        else:
            subprocess.run(("git", "pull", "--ff-only"), cwd=root, check=True)
            after = git(root, "rev-parse", "HEAD")
        code_changed = before != after or args.reexecuted
        if before != after and not args.reexecuted:
            forwarded = [
                flag
                for flag, enabled in (
                    ("--dry-run", args.dry_run),
                    ("--verbose", args.verbose),
                    ("--no-restart", args.no_restart),
                    ("--start", args.start),
                )
                if enabled
            ]
            os.execv(sys.executable, [sys.executable, str(root / "update.py"), *forwarded, "--reexecuted"])
        provisioner = Provisioner(root, dry_run=args.dry_run, verbose=args.verbose)
        unit_changed, config_changed, _ = provisioner.reconcile()
        should_restart = not args.no_restart and (
            code_changed or unit_changed or config_changed
        )
        provisioner.activate(restart=should_restart, start=args.start)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"update: {format_command_error(exc)}\n")
    except (RuntimeError, OSError) as exc:
        parser.exit(1, f"update: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

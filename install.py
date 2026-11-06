from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from runtime.provision import (
    Provisioner,
    format_command_error,
    require_production_root,
    require_supported_interpreter,
)


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        require_production_root(root)
        require_supported_interpreter(root)
        provisioner = Provisioner(root, dry_run=args.dry_run, verbose=args.verbose)
        unit_changed, config_changed, _ = provisioner.reconcile()
        provisioner.activate(restart=unit_changed or config_changed)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"install: {format_command_error(exc)}\n")
    except (RuntimeError, OSError) as exc:
        parser.exit(1, f"install: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

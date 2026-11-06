from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from back.config import EX_CONFIG, ConfigError, load_settings
from back.log import configure_logging
from back.service import run_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Contract review service", allow_abbrev=False)
    parser.add_argument("--check", action="store_true", help="validate configuration and exit")
    parser.add_argument("--config", type=Path, help="use an explicit INI configuration")
    args = parser.parse_args()
    configure_logging("INFO")
    logger = logging.getLogger(__name__)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        logger.error("Configuration error", extra={"structured": {"error": str(exc)}})
        return EX_CONFIG
    configure_logging(settings.log_level)
    if args.check:
        logger.info("Configuration is valid")
        return 0
    try:
        asyncio.run(run_service(settings))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

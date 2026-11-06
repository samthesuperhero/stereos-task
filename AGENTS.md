# Binding rules and conventions

These rules apply to everyone working in this repository, human or agent. The generic conventions and operational specifications live in `docs/CONVENTIONS.md`, `docs/CONTRACTS.md`, and `docs/ARCHITECTURE.md`. Record every meaningful generic decision in `docs/DECISIONS.md`. Keep all service-specific business logic, source-data expectations, and product decisions exclusively in `docs/SERVICE_SPECIFICATION.md`.

## Rules

1. **Documentation is a deliverable.** Update the relevant documentation in the same change as the code it describes. Use only English in project-authored READMEs, documentation, specifications, and comments; required source-data literals and user-facing domain strings may remain in their original language. Record decisions newest-first in `docs/DECISIONS.md`; never delete history, and supersede obsolete decisions instead of rewriting it.

2. **Python and asyncio.** The interpreter floor is declared only in `pyproject.toml` and must not be restated elsewhere. Runtime code is asyncio-first: all I/O is asynchronous and the event loop must never be blocked.

3. **Dependencies.** Use only `>=` lower bounds, without upper caps or exact/compatible pins. Declare every import, including currently transitive imports. The best-fitting dependency must be proposed to and explicitly approved by a human, then documented.

4. **Style.** Use Ruff only, with its default ruleset and the target configured in `pyproject.toml`. E501, import-order, and pyupgrade rules are not enforced; do not clean up long lines or legacy typing imports merely on sight. Follow `.editorconfig` for whitespace and encoding.

5. **Configuration.** Use flat INI at `/etc/stereos-task/stereos-task.ini`, mode `0444`, with no secrets. Precedence is code defaults, then INI, then environment variables where defined. Every configurable host-operational knob has an in-code default; correctness data is a code constant. An unparseable configuration exits `78` (`EX_CONFIG`). Retuning requires redeployment.

6. **Secrets.** Use flat, role-named files in the config directory, mode `0400`, one secret per file. Never commit or log secrets or put them in world-readable configuration. The installer enforces ownership and mode and asks for each value with echo disabled; it never invents one.

7. **Logging and errors.** Emit one JSON object per line to stdout with `ts` (ISO-8601 UTC), `level`, `logger`, `service`, `msg`, structured `extra`, and `exc` on exceptions. Unknown levels fall back to INFO. Never log secret values. Error payloads use `{"error":{"code","message","details"}}`.

8. **Versioning.** Keep SemVer only in `VERSION`; no other file restates the current value. Before a commit that changes code, bump PATCH by default, MINOR for a feature with PATCH reset to zero, and MAJOR only by explicit human decision. Documentation-only and root-only changes do not bump the version.

9. **Git.** Keep text LF-only through `.gitattributes`. Prefer `main` and ask before branching. Always stage explicit paths and propose a commit message, but never commit without explicit human confirmation. Never use blanket staging or commit-all flags. Commit extensionless Bash wrappers as executable mode `100755`.

10. **Install and update.** Provide idempotent `install.py`/`update.py` plus thin executable Bash wrappers. Administrators run `sudo ./install`. Both Python entry points and `runtime/provision.py` are pure stdlib because they run as root before the virtual environment exists. They refuse to run outside the canonical production checkout. Installation provisions an already-cloned tree without pulling. Update pulls, re-executes itself once if `HEAD` advances, reconciles, and restarts only when necessary. Reconciliation merges new configuration keys without changing values or removing keys, preserves comments and ordering, and retains a `*.ini.bak` backup.

11. **Service lifecycle.** systemd uses `Type=notify` with `sd_notify` readiness. `ExecStartPre` runs `--check`; invalid configuration exits `78`, and `RestartPreventExitStatus=78` prevents a crash loop. SIGTERM/SIGINT set an `asyncio.Event`, stop new work, drain in-flight work, close resources with bounded and isolated cleanup, and exit zero within `TimeoutStopSec`.

12. **Tests.** Use hermetic, OS-independent `pytest` and `pytest-asyncio` tests with asyncio auto mode. They must work on the Windows development box without PostgreSQL, network access, or heavy drivers; use lazy imports and fakes.

13. **Overlapping runs.** Never introduce overlapping backup runs. If a run is active when another trigger fires, skip the new trigger and emit a warning.

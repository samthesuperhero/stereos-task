# Engineering conventions

## Scope

These conventions are binding for implementation, review, installation, and operations. `AGENTS.md` is the short repository-level entry point. External behavior is specified in `docs/CONTRACTS.md`; component boundaries are described in `docs/ARCHITECTURE.md`.

## Change and decision hygiene

- Documentation changes ship in the same change as the behavior they describe.
- Project-authored READMEs, documentation, specifications, and comments use English only. Original source materials and required user-facing or source-data literals are not translated merely to satisfy this rule.
- Every meaningful decision is recorded in `docs/DECISIONS.md`, newest first. Existing entries are retained; later decisions supersede earlier ones explicitly.
- Do not represent planned or open choices as implemented behavior.
- Documentation-only and repository-root-only changes do not change `VERSION`.

## Language and concurrency

- The supported interpreter floor has exactly one source: `pyproject.toml`. Do not duplicate its value in documentation, scripts, or other configuration.
- Runtime code is asyncio-first. File, process, network, and service I/O must use non-blocking asynchronous interfaces.
- CPU-heavy or unavoidably synchronous work must not run directly on the event loop; any offload design must be documented and tested.
- Shutdown uses an `asyncio.Event` as the stop signal. Signal handlers initiate shutdown rather than performing application cleanup themselves.

## Dependencies

- A dependency must be proposed with its purpose and fit, explicitly approved by a human, declared in `pyproject.toml`, and documented before use.
- Every direct import must be declared even if another package currently installs it transitively.
- Version requirements use lower bounds only. Do not add upper caps, exact pins, or compatible-release pins.
- Installation and provisioning code that runs before the virtual environment is created may import only the Python standard library. This includes `install.py`, `update.py`, their import chains, and `runtime/provision.py`.
- Heavy runtime drivers are lazy imports so the hermetic test suite can run without them.

## Formatting and static checks

- Ruff is the sole Python style tool. It uses its default ruleset and the target configured in `pyproject.toml`.
- E501, import-order, and pyupgrade checks are not enforced. Avoid unrelated line-length, import-order, or legacy-typing cleanup.
- Whitespace and encoding follow `.editorconfig`; tracked text uses LF line endings according to `.gitattributes`.
- Extensionless Bash wrappers must retain executable mode `100755`.

## Configuration and secrets

- Configuration is a flat INI file with no secret material. Each host-operational setting has an in-code default; business or correctness rules remain code constants.
- Precedence is code defaults, then INI, then explicitly supported environment variables.
- Parsing failure is a configuration error and must exit `78` (`EX_CONFIG`).
- Secrets are separate role-named files, one value per file, with mode `0400` and enforced ownership. They are never committed, logged, invented, or copied into the INI file.
- Configuration reconciliation operates key by key: add newly introduced keys, preserve existing values and all existing keys, preserve comments and ordering, and save the pre-merge file as `*.ini.bak`.

## Version control and releases

- `VERSION` is the only location containing the current SemVer value.
- Code changes require a version bump before committing: PATCH normally, MINOR for a feature with PATCH reset, and MAJOR only with explicit human approval.
- Work on `main` by default; ask before creating a branch.
- Stage only explicit pathspecs and propose a commit message. Never use blanket staging or commit-all flags.
- Preparing a change does not authorize committing it. A commit requires explicit human confirmation.

## Testing

- Tests use `pytest` and `pytest-asyncio` with asyncio auto mode.
- Tests are hermetic and OS-independent: no network, PostgreSQL, production host, or installed heavy drivers are required on the Windows development machine.
- Use fakes at external boundaries and lazy imports for optional or heavy integrations.
- Tests must cover behavior, failure handling, and lifecycle behavior relevant to the change. Service-specific acceptance coverage is defined separately in the service specification.

## Operational safety

- Install and update operations must be idempotent and support dry-run and verbose modes with unabbreviated command-line options.
- Production entry points refuse to run outside the canonical production checkout.
- Backup-style scheduled work must never overlap. A trigger arriving during an active run is skipped and logged at warning level.

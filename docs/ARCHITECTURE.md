# Architecture

## Current state

The repository contains specifications and source materials. No application, framework, persistence layer, installer, service unit, or deployment path has been implemented. The boundaries below are generic required design constraints, not a claim that components already exist. Business-processing architecture belongs exclusively in `docs/SERVICE_SPECIFICATION.md`.

## Application topology

- `back/` contains the asyncio Python backend, deployed as a systemd service.
- `front/` contains only static HTML, CSS, and JavaScript. Frontend frameworks and a frontend build stack are not used.
- The frontend is served by nginx directly from its installed directory on the Linux host.
- The backend listens on port `61070` and is not exposed directly; nginx reverse-proxies backend requests to that port.
- `install.py` creates the nginx configuration that serves the static frontend and proxies to the backend.
- The nginx public listen address and port and the absolute static installation path remain deployment decisions.

## Runtime boundary

Runtime Python code is asyncio-first and must not block the event loop. The application exposes two operational modes:

- normal service execution, including readiness notification and graceful shutdown;
- `--check`, which validates configuration and exits `78` on invalid configuration.

Configuration consists of non-secret flat INI settings with code defaults and explicitly supported environment overrides. Secrets are read from separate restricted files and remain outside logs and structured errors. The application writes JSON lines to stdout and leaves journal capture to journald.

## Provisioning boundary

Installation and updating are separate from the runtime dependency environment:

- `install` and `update` are thin executable Bash wrappers.
- `install.py`, `update.py`, and `runtime/provision.py`, including their import chains, use only the standard library.
- They run as root before a virtual environment exists and refuse execution outside the canonical production checkout.
- Installation reconciles an existing clone without fetching; update owns pulling and one conditional re-execution.
- System package, user, filesystem, virtual-environment, configuration, secret, and service changes are reconciled idempotently.

The exact canonical production checkout path is not yet selected and must be fixed before implementing the guard.

## Service boundary

A future systemd unit owns process lifecycle:

- `Type=notify` coordinates readiness through `sd_notify`.
- `ExecStartPre` invokes `--check`, and exit `78` is excluded from automatic restart.
- SIGTERM/SIGINT trigger an `asyncio.Event`-based drain.
- Resource shutdown is bounded and isolated so one close failure does not prevent the remaining cleanup.
- Restart follows update only when code, unit, or configuration actually changed, unless command flags direct otherwise.

## Test boundary

Tests run locally and hermetically on Windows without network, PostgreSQL, or heavy drivers. External services and drivers sit behind lazy-imported boundaries that can be replaced by fakes. Tests must exercise the behavior and failure modes relevant to each component without requiring production infrastructure.

## Operational evolution

Backup-style work, if introduced, requires a single-active-run guard; later triggers are skipped with a warning rather than allowed to overlap. Scaling and business-specific access-control considerations are specified separately in the service specification.

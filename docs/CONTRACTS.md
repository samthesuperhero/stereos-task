# Operational specifications and behavioral contracts

## Scope

This document defines generic service operational behavior. It contains no business-domain rules or source-data expectations; those belong exclusively in `docs/SERVICE_SPECIFICATION.md`. The backend, installers, unit, and nginx assets implement this contract; real production-host reconciliation remains an operational verification task.

## Deployment topology contract

- The backend resides in `back/` and runs as an asyncio Python systemd service.
- The frontend resides in `front/` and uses only static HTML, CSS, and JavaScript, without frontend frameworks.
- nginx serves the frontend directly from its installed directory on the Linux host.
- nginx reverse-proxies backend requests to port `61070`; the backend is not exposed directly.
- `install.py` creates the nginx configuration for static frontend hosting and backend proxying. Repeated installation must leave an already-correct nginx configuration unchanged.

## Configuration contract

- Production configuration path: `/etc/stereos-task/stereos-task.ini`.
- Format: flat INI, no secrets, filesystem mode `0444`.
- Precedence: code defaults, then INI, then supported environment variables.
- Invalid or unparseable configuration exits `78` (`EX_CONFIG`).
- `--check` validates configuration without starting normal service work.
- Changing operational tuning is a redeployment action; correctness data is not externally configurable.
- Secret files live in the same configuration directory, have role-based names, contain one value each, and use mode `0400` with enforced ownership.

## Logging and error contract

Each log record is one JSON object on one stdout line, suitable for journald capture. Standard fields are:

- `ts`: ISO-8601 UTC timestamp;
- `level`: record level, with unknown configured levels falling back to INFO;
- `logger`: logger name;
- `service`: service identifier;
- `msg`: human-readable message;
- `extra`: structured contextual data;
- `exc`: exception information when applicable.

Secrets must never appear in any field. Structured error payloads use exactly this envelope shape:

```json
{"error":{"code":"...","message":"...","details":{}}}
```

## Installer and updater contract

- Deliver `install.py` and `update.py`, plus executable `install` and `update` Bash wrappers that bootstrap a qualifying interpreter. Provisioning reads the interpreter lower bound from `pyproject.toml` without restating it and validates existing and newly created virtual environments by executing their interpreters.
- Administrators install an already-cloned checkout with `sudo ./install`; installation never performs `git pull`.
- Both tools run as root before the virtual environment exists and use only the standard library in their import chains and `runtime/provision.py`.
- Both refuse to run outside `/opt/stereos-task`, the canonical production checkout, and reject an unsupported interpreter before Git or host mutations.
- Both are idempotent: re-running an already-correct host makes no changes and exits zero. Missing, obsolete, or broken virtual environments are built and validated in a staging directory before replacement.
- Both support `--dry-run` and `--verbose`; argument parsing uses `allow_abbrev=False`.
- Update additionally supports `--no-restart` and `--start`.
- Update performs `git pull`, re-executes once if `HEAD` changed, then reconciles with the updated code.
- Backend restart occurs only if the unit, code, or INI configuration changed, subject to the update flags. Static, nginx, ownership, mode, user, virtualenv, and firewall repairs do not independently restart it.
- Unknown installation values are requested interactively. Secret prompts disable echo; values are never invented.
- Existing and example INI content is validated before host provisioning mutations. Reconciliation adds new example keys without altering values, deleting keys, or losing comments/order. The exact pre-merge file, including an empty file, is atomically retained as `*.ini.bak` before the live INI is replaced; backup failure leaves the live INI unchanged.
- Frontend reconciliation mirrors the repository into the dedicated static directory and removes stale files without following destination symlinks. Expected symlinks are replaced rather than traversed, changed content is copied through secure temporary files and atomically renamed, and unexpected type collisions fail safely. Static directories use mode `0755` and files `0644`; existing configuration, state, and static directory modes are reconciled rather than checked only at creation.
- Provisioning validates nginx with `nginx -t` before lifecycle changes, reloads or restarts it after configuration changes, and starts it when inactive even if its configuration is unchanged.
- Failed captured subprocesses report their command, exit status, and useful stderr or stdout through the entry-point diagnostic.
- When firewalld is active, TCP ports 80 and 443 are opened permanently; inactive firewalld and all SELinux settings are left unchanged. Firewall reconciliation does not trigger a backend restart.

For installation, a root administrator clones into `/root/stereos-task`, synchronizes the tree into `/opt/stereos-task` with `rsync` while preserving the production `.venv`, and runs `./install` from the canonical checkout. For updates, the administrator pulls both checkouts: first in `/root/stereos-task`, then through `./update` in `/opt/stereos-task`, without an intervening `rsync` that would hide the production `HEAD` change.

## systemd and shutdown contract

- The unit uses `Type=notify` and sends readiness through `sd_notify`.
- `ExecStartPre` invokes the application with `--check`.
- `RestartPreventExitStatus=78` leaves invalid configuration in `failed` rather than restart-looping.
- SIGTERM and SIGINT set an `asyncio.Event`.
- On shutdown, stop accepting new work, allow in-flight work to drain, and close pools/resources with bounded and individually isolated cleanup.
- Successful graceful shutdown exits zero within the unit's `TimeoutStopSec`.

## Scheduling contract

Only one backup-style run may be active at a time. A new trigger during an active run is skipped and produces a warning; it must not queue an overlapping run.

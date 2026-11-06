# Architecture

## Current state

The repository contains a stdlib-only asyncio backend, static frontend, hermetic tests, and production provisioning assets. No framework or persistence layer is used. The boundaries below describe the implemented topology; business-processing architecture belongs exclusively in `docs/SERVICE_SPECIFICATION.md`.

## Application topology

- `back/` contains the asyncio Python backend, deployed as a systemd service.
- `front/` contains only static HTML, CSS, and JavaScript. Frontend frameworks and a frontend build stack are not used.
- The frontend is served by nginx directly from its installed directory on the Linux host.
- The backend listens on port `61070` and is not exposed directly; nginx reverse-proxies backend requests to that port.
- `install.py` creates the nginx configuration that serves the static frontend and proxies to the backend.
- Fedora nginx loads `/etc/nginx/conf.d/stereos.filestreamcloud.org.conf`. It redirects HTTP port 80 to HTTPS, serves `stereos.filestreamcloud.org` on port 443 with the host's Let’s Encrypt certificate, and applies explicit security and static-cache headers.

## Runtime boundary

Runtime Python code is asyncio-first and must not block the event loop. The application exposes two operational modes:

- normal service execution, including readiness notification and graceful shutdown;
- `--check`, which validates configuration and exits `78` on invalid configuration.

Configuration consists of non-secret flat INI settings with code defaults and explicitly supported environment overrides. Request and shutdown timeouts must be finite and positive; shutdown draining is capped at 20 seconds to preserve the unit's 30-second stop margin. Secrets are read from separate restricted files and remain outside logs and structured errors. The application writes JSON lines to stdout and leaves journal capture to journald.

HEAD uses the corresponding GET representation and content length for health, configuration, and static responses. The HTTP serializer suppresses the body for both successful and error HEAD responses.

## Provisioning boundary

Installation and updating are separate from the runtime dependency environment:

- `install` and `update` are thin executable Bash wrappers.
- `install.py`, `update.py`, and `runtime/provision.py`, including their import chains, use only the standard library.
- They run as root before a virtual environment exists and refuse execution outside the canonical production checkout. The interpreter floor is read from `pyproject.toml`; existing virtualenv interpreters are executed for health/version checks, and replacements are staged before activation.
- For installation, the administrator clones into `/root/stereos-task` and synchronizes it with `rsync` into the canonical `/opt/stereos-task` checkout.
- Installation reconciles the synchronized clone without fetching. Routine updates pull in the root checkout and then invoke update in production without pre-synchronizing, preserving `HEAD`-based code-change detection and one conditional re-execution.
- System package, user, filesystem, virtual-environment, configuration, secret, and service changes are reconciled idempotently. Existing directory and static-file modes are corrected, not merely inspected at creation.

The canonical production checkout is `/opt/stereos-task`; both provisioning entry points enforce this path. The static frontend is mirrored at `/var/www/stereos-task`, including removal of stale files and empty directories. Static reconciliation never follows destination symlinks and uses secure temporary files plus atomic replacement. INI content is validated before host provisioning and backed up atomically before replacement. The unit is named `stereos-task.service`. Inactive nginx is started even when its configuration is unchanged; backend restarts remain limited to code, unit, or INI changes. When firewalld is active, provisioning permanently opens TCP ports 80 and 443 without restarting the backend. SELinux settings, certificate lifecycle, IPv6 listeners, and unrelated nginx sites are not managed.

## Service boundary

The `stereos-task.service` systemd unit owns process lifecycle:

- `Type=notify` coordinates readiness through `sd_notify`.
- `ExecStartPre` invokes `--check`, and exit `78` is excluded from automatic restart.
- SIGTERM/SIGINT trigger an `asyncio.Event`-based drain.
- Resource shutdown is bounded and isolated so one close failure does not prevent the remaining cleanup.
- Restart follows update only when code, unit, or configuration actually changed, unless command flags direct otherwise.

## Test boundary

Tests run locally and hermetically on Windows without network, PostgreSQL, or heavy drivers. External services and drivers sit behind lazy-imported boundaries that can be replaced by fakes. Tests must exercise the behavior and failure modes relevant to each component without requiring production infrastructure.

## Operational evolution

Backup-style work, if introduced, requires a single-active-run guard; later triggers are skipped with a warning rather than allowed to overlap. Scaling and business-specific access-control considerations are specified separately in the service specification.

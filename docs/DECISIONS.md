# Decision log

New entries appear first. Entries are append-only history: do not delete or silently rewrite them. A later entry must explicitly identify any earlier decision it supersedes. This log contains only generic engineering and operational decisions; service-specific business and data decisions live in `docs/SERVICE_SPECIFICATION.md`.

## 2026-11-06 — Make provisioning no-follow, atomic, and explicitly bounded

**Status:** Accepted

**Context:** Review confirmed that static destination symlinks could redirect root writes, existing permissions and virtualenvs were insufficiently validated, malformed INI could cause partial reconciliation, backups followed live replacement, and unrelated repairs restarted the backend. Runtime timeout and HEAD validation also needed explicit boundaries.

**Decision:** Read the interpreter floor from `pyproject.toml`, execute and stage virtualenv interpreters before replacement, reconcile static content without following destination symlinks, use secure temporary files and atomic replacement, enforce existing directory/file modes, validate INI before host mutations, and back up every existing INI before replacement. Recover inactive nginx independently of configuration changes, restrict backend restarts to code/unit/INI changes, expose captured subprocess diagnostics, require finite positive request timeouts, cap shutdown draining at 20 seconds, and serialize HEAD with GET-equivalent lengths but no body.

**Consequences:** Provisioning remains stdlib-only, idempotent, dry-run aware, and safe against the reviewed symlink and backup-failure cases. Host operational choices retain their existing defaults, and no dependency is introduced. Business-specific parser and evidence decisions are recorded separately in `docs/SERVICE_SPECIFICATION.md`.

## 2026-11-06 — Preserve code-change detection by pulling both checkouts during updates

**Status:** Accepted

**Context:** Synchronizing Git metadata into production before running update would make the production `HEAD` equal to its pulled target before update begins, suppressing the code-change signal used to restart the backend.

**Decision:** Use `rsync` only for initial installation. During routine updates, pull in `/root/stereos-task`, then run `./update` in `/opt/stereos-task` without an intervening synchronization so update performs the production pull itself.

**Consequences:** Both checkouts retrieve the same revision through Git, and production update retains restart detection and conditional self-re-execution. This supersedes the update-time synchronization portion of “Stage Git operations in root while retaining the canonical production checkout”; its installation workflow remains unchanged.

## 2026-11-06 — Stage Git operations in root while retaining the canonical production checkout

**Status:** Accepted

**Context:** The administrator works as root and performs Git operations under `/root`, while the service guard and hardened unit already require `/opt/stereos-task`.

**Decision:** Use `/root/stereos-task` as the administrator's source checkout. Clone or pull there, then synchronize the complete tree into `/opt/stereos-task` with `rsync -a --delete`, excluding the production virtual environment and development caches. Run install and update only from `/opt/stereos-task`.

**Consequences:** Git operations remain under `/root` without moving application execution into a home directory or weakening systemd filesystem protections. The source and production checkouts retain Git metadata, and update still performs its final pull and conditional self-re-execution in the canonical checkout.

## 2026-11-06 — Reconcile public firewall access and mirror deployed static files

**Status:** Accepted

**Context:** Fedora host decisions are now explicit: SELinux is disabled, firewalld may be active, deleted frontend files must not remain deployed, HTTPS is confirmed, IPv4 alone is required, unrelated nginx sites are untouched, and updates may rely on `git pull --ff-only` behavior in a dirty checkout.

**Decision:** When firewalld is active, query permanent TCP ports 80 and 443, add only missing ports, and reload only after a change. Do not trigger a backend restart for firewall reconciliation. Mirror the repository frontend into the dedicated static root and remove stale files and empty directories. Leave SELinux, certificate lifecycle, unrelated nginx configuration, and dirty-checkout update behavior unchanged; retain HSTS and IPv4-only listeners.

**Consequences:** Dry-run uses read-only queries to inspect actual firewall state. Deletion is confined to the dedicated `/var/www/stereos-task` tree. Existing dirty-checkout updates continue to succeed or fail according to Git rather than a separate preflight guard.

## 2026-11-06 — Use English for project-authored documentation and comments

**Status:** Accepted

**Context:** The project needs a consistent language for maintainers and automated contributors.

**Decision:** Write all project-authored READMEs, documentation, specifications, and comments in English. Preserve original assignment/source materials and required user-facing or source-data literals where translating them would alter their meaning or expected behavior.

**Consequences:** Existing project-authored prose is converted to English, while the original Russian assignment, source documents, supplier names, and the required no-data UI literal remain valid domain data rather than project prose.

## 2026-11-06 — Target Fedora nginx with the public HTTPS virtual host

**Status:** Accepted

**Context:** The production host runs Fedora and includes `/etc/nginx/conf.d/` in its nginx configuration. The public hostname and existing Let’s Encrypt certificate paths are now fixed.

**Decision:** Provision one `/etc/nginx/conf.d/stereos.filestreamcloud.org.conf` file through `dnf`-based nginx installation when needed. Serve `stereos.filestreamcloud.org` over HTTPS using `/etc/letsencrypt/live/stereos.filestreamcloud.org/fullchain.pem` and `privkey.pem`; redirect HTTP to HTTPS. Apply the specified HSTS, content-type, frame, referrer, static no-cache, and proxy timeout/header settings. Validate with `nginx -t` and use `reload-or-restart` so fresh installations also start correctly.

**Consequences:** Certificate issuance and renewal remain host responsibilities, and installation fails validation if the certificate files are unavailable. No `sites-available`/`sites-enabled` links are created. This supersedes the Debian/Ubuntu package reconciliation and port-80-only listener portions of “Use a stdlib asyncio runtime and fixed production identifiers”.

## 2026-11-06 — Use a stdlib asyncio runtime and fixed production identifiers

**Status:** Accepted

**Context:** The prototype needs a runnable service without implicitly introducing dependencies, and the installers require fixed paths and unit identifiers.

**Decision:** Implement the runtime with the Python standard library only. Use the canonical checkout `/opt/stereos-task`, static root `/var/www/stereos-task`, state directory `/var/lib/stereos-task`, service user and unit name `stereos-task`, and an nginx listener on port 80. Tests use the already-mandated pytest and pytest-asyncio tools. No secret role is introduced because the prototype has no external credentials.

**Consequences:** No runtime dependency approval is required. The HTTP implementation intentionally covers only the prototype's required JSON/static routes and connection model. Debian/Ubuntu package reconciliation installs nginx when absent. This supersedes the open canonical-path, unit-name, framework, and secret-role portions of “Defer implementation-specific technology and deployment identifiers”.

## 2026-11-06 — Split the service into a Python backend and static frontend behind nginx

**Status:** Accepted

**Context:** The service needs explicit application and deployment boundaries before implementation begins.

**Decision:** Place the backend in `back/` and run it as an asyncio Python systemd service. Place the frontend in `front/` and implement it only with static HTML, CSS, and JavaScript, without frontend frameworks. Install and serve the frontend as static files from its directory on the Linux host. Put the backend behind an nginx reverse proxy and use backend port `61070`. `install.py` must create the nginx configuration for static frontend hosting and backend proxying.

**Consequences:** The backend and frontend have separate runtime responsibilities: systemd manages the backend, while nginx serves frontend files and proxies backend requests. No frontend framework or frontend build stack is approved or required. The nginx public listen address and port, static installation path, and other unresolved deployment identifiers remain open. This supersedes the application-topology and framework portions of “Defer implementation-specific technology and deployment identifiers”; its other open choices remain unchanged.

## 2026-11-06 — Separate generic and service-specific specifications

**Status:** Accepted

**Context:** Generic engineering and operational documentation must remain reusable and independent of business rules, source materials, and task-specific acceptance criteria.

**Decision:** Keep service-specific business logic, source-data expectations, and product decisions exclusively in `docs/SERVICE_SPECIFICATION.md`. Keep generic rules in `AGENTS.md` and generic engineering, operational, and architecture documentation in the other files under `docs/`.

**Consequences:** This supersedes the former placement of service-business decisions in this log. The affected decision is preserved without substantive change in the service specification. Generic documents must not gain fixture values, domain rules, or task-specific acceptance details.

## 2026-11-06 — Establish binding engineering and operational conventions

**Status:** Accepted

**Context:** The repository needs stable implementation, documentation, installation, and operational rules before application code is introduced.

**Decision:** Adopt `AGENTS.md` as the concise binding ruleset, with detailed conventions in `docs/CONVENTIONS.md`, external behavior in `docs/CONTRACTS.md`, and component boundaries in `docs/ARCHITECTURE.md`. Documentation travels with code changes. Dependencies require explicit human proposal and approval. Interpreter versioning, formatting, configuration, secrets, logging, SemVer, Git, idempotent provisioning, systemd lifecycle, hermetic testing, and non-overlapping runs follow the rules recorded there.

**Consequences:** No dependency or framework is implicitly approved by this decision. Documentation-only changes do not bump `VERSION`. Production installers cannot be completed until the canonical checkout path is chosen.

## 2026-11-06 — Defer implementation-specific technology and deployment identifiers

**Status:** Accepted

**Context:** No application stack or production layout has been selected, and dependency choices require human approval.

**Decision:** Record only required logical boundaries for now. Do not claim that a framework, database, LLM, canonical production checkout path, systemd unit name, or secret role has already been chosen. Propose these with their trade-offs when implementation begins; obtain explicit human approval for each dependency.

**Consequences:** The repository remains documentation-only and has no runnable application yet. Open implementation choices must be resolved in later changes and recorded here.

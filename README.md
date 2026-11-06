# stereos-task

A local prototype for procurement specialists: it accepts multiple sample TXT files, shows effective contract amounts and delivery dates, lists proposals separately, and links every result to an exact source quotation. It uses neither an LLM nor paid APIs.

## Launch and verification

Use the Python version required by `pyproject.toml`. The runtime uses only the standard library. From the repository root:

```bash
python -m back
```

Open `http://127.0.0.1:61070`, select all six files from `data/`, and start the review. The review date and report cutoff are populated automatically. Quick-action buttons answer amount and delivery-date questions for the selected contract; a separate report shows deliveries before the selected date and unapproved delivery changes.

Validate configuration without starting the service:

```bash
python -m back --check
python -m back --check --config deploy/stereos-task.ini
```

Install the repository-mandated test and style tools, then run their checks:

```bash
python -m pip install "pytest>=8" "pytest-asyncio>=0.23" "ruff>=0.6"
python -m pytest -q
python -m ruff check .
```

### API

`GET /api/health` returns readiness, and `GET /api/config` returns the initial interface dates. `POST /api/review` accepts JSON:

```json
{
  "review_date": "2026-03-10",
  "delivery_cutoff": "2026-04-01",
  "documents": [{"name": "contract.txt", "text": "Contents of the uploaded TXT document"}]
}
```

The response contains `contracts`, `review_items`, `documents`, and `delivery_report`. A missing value is `null`; an extracted value has `evidence` containing the upload-order `document_id`, filename, exact quotation, paragraph number, and character offset. Review items classify delivery changes as `unapproved`, `approved_pending`, `unresolved`, or `none`; only `unapproved` items appear in the unapproved-delivery report. Errors use the `{"error":{"code","message","details"}}` envelope.

## Production

The administrator works as `root` and pulls Git changes into `/root/stereos-task`. The canonical production checkout remains `/opt/stereos-task`; the installer and updater refuse to run anywhere else. Use `rsync` between these locations so the production service retains its existing permissions and hardening.

### Fresh installation on Fedora

**1. Log in as root and install the required host tools.**

```bash
whoami
cd /root
dnf install -y git rsync python3
```

`whoami` must print `root`. The application itself supports the interpreter version declared in `pyproject.toml`.

**2. Set the repository URL and clone the source checkout.**

Replace the example URL with the actual HTTPS or SSH repository URL:

```bash
export REPOSITORY_URL="https://git.example.com/stereos-task.git"
cd /root
git clone "$REPOSITORY_URL" stereos-task
cd /root/stereos-task
git status --short --branch
```

**3. Confirm that the existing certificate and private key are available.**

```bash
ls -l /etc/letsencrypt/live/stereos.filestreamcloud.org/fullchain.pem
ls -l /etc/letsencrypt/live/stereos.filestreamcloud.org/privkey.pem
```

Both commands must succeed. Certificate issuance and renewal remain external to this installer.

**4. Create and synchronize the canonical production checkout.**

```bash
mkdir -p /opt/stereos-task
rsync -a --delete \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  /root/stereos-task/ /opt/stereos-task/
cd /opt/stereos-task
```

The trailing slashes are required: they synchronize the directory contents rather than nesting one directory inside another. The `.venv` exclusion preserves the production virtual environment.

**5. Optionally preview provisioning, then run the installer.**

```bash
cd /opt/stereos-task
./install --dry-run --verbose
./install --verbose
```

Installation does not pull from Git. It validates the running interpreter against `pyproject.toml`, creates the service user, and creates or stages a replacement virtual environment when the existing one is missing, obsolete, or broken. Static mirroring does not follow destination symlinks and reconciles file and directory modes. The installer also installs the read-only INI and systemd unit and writes `/etc/nginx/conf.d/stereos.filestreamcloud.org.conf`. If nginx is absent, the installer runs `dnf install -y nginx`; inactive nginx is started even when its configuration is unchanged. When firewalld is active, it permanently opens TCP ports 80 and 443. Other nginx sites and SELinux settings are left unchanged.

**6. Verify configuration, services, nginx, and the public API.**

```bash
cd /opt/stereos-task
./.venv/bin/python -m back --check --config /etc/stereos-task/stereos-task.ini
systemctl status stereos-task.service --no-pager
systemctl status nginx --no-pager
nginx -t
curl --fail https://stereos.filestreamcloud.org/api/health
```

The final command should return a JSON response containing `"status":"ok"`.

### Update an existing installation

**1. Pull the desired source revision into the root checkout.**

```bash
cd /root/stereos-task
git pull --ff-only
git status --short --branch
```

If Git reports conflicting local changes, stop and resolve them deliberately; do not discard them with a reset.

**2. Optionally preview reconciliation, then run the updater from production.**

Do not run `rsync` before this step. The updater must observe the production `HEAD` change so it knows that code changed and can restart the backend correctly.

```bash
cd /opt/stereos-task
./update --dry-run --verbose
./update --verbose
```

Update performs `git pull --ff-only` in the canonical checkout, re-executes itself once if `HEAD` advances, reconciles host configuration, and restarts the backend only for code, unit, or INI changes. Both the root and production checkouts therefore retrieve the same revision through Git. Use `./update --no-restart` to suppress a backend restart or `./update --start` to request startup explicitly. Static, nginx, ownership, mode, virtualenv, and firewall repairs do not independently restart the backend.

**3. Verify the updated installation.**

```bash
cd /opt/stereos-task
./.venv/bin/python -m back --check --config /etc/stereos-task/stereos-task.ini
systemctl status stereos-task.service --no-pager
systemctl status nginx --no-pager
nginx -t
curl --fail https://stereos.filestreamcloud.org/api/health
```

INI reconciliation validates existing content before host provisioning, preserves existing values, ordering, and comments, and atomically saves the exact previous file—including an empty file—as `*.ini.bak` before replacing the live INI. Nginx redirects HTTP to HTTPS and applies the configured security, caching, and proxy headers and timeouts. Provisioning runs `nginx -t` before nginx lifecycle changes, reloads or restarts after configuration changes, and starts inactive nginx when configuration is unchanged.

Settings use code defaults, then `/etc/stereos-task/stereos-task.ini`, then environment variables named `STEREOS_TASK_HOST`, `STEREOS_TASK_PORT`, `STEREOS_TASK_STATIC_DIR`, `STEREOS_TASK_MAX_REQUEST_BYTES`, `STEREOS_TASK_REQUEST_TIMEOUT_SECONDS`, `STEREOS_TASK_SHUTDOWN_TIMEOUT_SECONDS`, and `STEREOS_TASK_LOG_LEVEL`. The default port is `61070`. Request and shutdown timeouts must be finite and positive; shutdown draining is capped at 20 seconds to preserve the systemd stop margin. The prototype requires no secrets. systemd uses `Type=notify`, a configuration pre-check, and graceful request draining.

## Product note

**User and assumptions.** A procurement specialist reviews a set of documents on a selected date. The text determines whether both parties signed a document and when it takes effect; only an effective signed amendment changes active terms. Unsigned or duplicate-number contracts, letters, drafts, ambiguous links, invalid source dates, and conflicts require review rather than inferred effective values. Filenames do not determine priority, and upload-order document IDs keep evidence links unambiguous when filenames repeat.

**Architecture.** The browser reads TXT files and sends JSON to the asyncio backend. Classification and extraction rules link documents and apply amendments; the frontend displays the table, evidence, and original text. In production, nginx serves static files and proxies API requests. There is no persistent state or database.

**Three decisions and trade-offs.** (1) The standard library replaces a web framework: there are no runtime dependencies, but the HTTP server supports only the required protocol subset. (2) Deterministic rules replace an LLM: results are reproducible and precisely linked to sources, but input must resemble the Russian-language samples. (3) Stateless JSON without a database simplifies the local scenario but provides no history, persistence, or collaboration. Synchronous static-file reads use `asyncio.to_thread` to avoid blocking the event loop.

**Five client questions:** 1) Which real templates and wording variants are mandatory? 2) How are signatures and effective dates verified? 3) How should conflicting amendments be resolved? 4) Who may view and modify each document set? 5) Are history, export, and accounting-system integration required?

**Metrics.** The percentage of values with correct quotations on a labeled sample (target 100%); time required to review a complete document set compared with manual reading (target at least 50% faster).

**Scale and access control.** At 100,000 documents, the design needs a queue, background workers, a database, full-text indexing, pagination, and resource limits. The server must enforce tenant/role access for every source document; quotations and links must not bypass authorization.

**Next improvements:** 1) support more wording and conflict-resolution cases; 2) persist document sets and history with auditing; 3) add SSO/RBAC and source-level authorization.

**Limitations and remaining tasks.** There is no OCR, PDF/DOCX support, arbitrary chat, result persistence, or authorization. Real Fedora/nginx/systemd provisioning and documents differing substantially from the samples still require verification. The initial implementation took approximately 20 minutes in one AI session, based on file timestamps from implementation through verification.

## AI-assisted development report

The tool was Kimi Code CLI. Representative requests were: "create the backend strictly according to the repository documents and constraints," "verify extraction against all six sources and add regression tests," and "diagnose failures without bypassing standard checks." One characteristic AI error classified a letter mentioning an amendment as an amendment itself, while an advance-payment line produced a competing total. End-to-end output and pytest exposed both errors; classification priority and the amount-context pattern were corrected and covered by tests. Windows tests also exposed eager imports of Unix `pwd/grp`; those imports were moved into Linux-only provisioning operations.

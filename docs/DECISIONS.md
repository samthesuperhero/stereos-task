# Decision log

New entries appear first. Entries are append-only history: do not delete or silently rewrite them. A later entry must explicitly identify any earlier decision it supersedes. This log contains only generic engineering and operational decisions; service-specific business and data decisions live in `docs/SERVICE_SPECIFICATION.md`.

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

# stereos-task

Service implementation repository. The application is not implemented yet; the repository currently contains requirements, source materials, and specifications.

## Contents

- `task/` — original assignment materials.
- `data/` — supplied source materials.
- `back/` — planned asyncio Python backend and systemd service.
- `front/` — planned static HTML, CSS, and JavaScript frontend, without frameworks.
- `AGENTS.md` — binding generic repository rules for contributors and agents.
- `docs/CONVENTIONS.md` — generic engineering, dependency, style, Git, and testing conventions.
- `docs/CONTRACTS.md` — generic configuration, logging, installer, and service behavior.
- `docs/ARCHITECTURE.md` — generic operational boundaries and current implementation status.
- `docs/DECISIONS.md` — newest-first generic engineering and operational decision history.
- `docs/SERVICE_SPECIFICATION.md` — the single source for service business logic, source-data expectations, product decisions, and task-specific acceptance requirements.

## Working on the repository

Read `AGENTS.md` and the detailed documents before making changes. Keep generic conventions separate from service-specific behavior. Update relevant documentation in the same change as code, record meaningful decisions in the appropriate file, and obtain explicit human approval before adding dependencies or committing. Installation and test commands will be documented when the corresponding implementation exists.

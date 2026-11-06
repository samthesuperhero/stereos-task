# Service specification

## Status and ownership

This is the single repository location for service-specific business logic, source-data expectations, product decisions, and task-specific acceptance requirements. Generic engineering and operational requirements remain in `AGENTS.md` and the other documents under `docs/`.

The source assignment is `task/PO_vibecoding_task.md`; supplied source materials are in `data/`. The prototype implements the required local multi-file review flow. This file remains the source of business rules and acceptance requirements.

## Purpose and user

The primary user is a procurement specialist checking supply terms without rereading every source document. The local prototype accepts multiple TXT files and presents a table with contract number, supplier, amount in rubles, and delivery date as of the review date.

The supplied scenario uses a review date of **10 March 2026**. File names and upload timestamps do not establish document priority.

## Effective-terms business logic

- Only an amendment signed by both parties and effective by the review date changes active contract terms.
- Supplier letters, proposals, and unsigned drafts are displayed separately as items requiring review; they never replace active terms.
- Supporting documents must be linked to their contracts. If a relationship or legal status cannot be resolved reliably, explicitly require human review instead of guessing.
- Extract values from uploaded text. Do not hardcode answers, amounts, dates, or behavior keyed to specific fixture file names.
- A changed value must identify the document that changed it.
- Unapproved proposed changes remain visible but distinct from effective values.

## Extraction and evidence

- Every amount and delivery date must have verifiable evidence: source file name, exact quote, and navigation to the corresponding source paragraph.
- If information is absent, display `нет данных`; never infer or invent a value.
- Internal limits, payment amounts, payment deadlines, and other similarly shaped values must not be mistaken for total contract value or delivery date.
- The interface must preserve the distinction between effective terms, missing values, proposed changes, and unresolved review states.

## Logical processing flow

1. Accept multiple TXT files through a local interface using asynchronous I/O.
2. Classify contracts, amendments, letters, and drafts from document content and status.
3. Link supporting documents to contracts, surfacing ambiguous links for review.
4. Determine active terms at the review date by applying only bilateral signed amendments already in force.
5. Extract contract number, supplier, amount, and delivery date while retaining exact source spans and paragraph locations.
6. Present effective values, missing values, proposed changes, and evidence without conflating their statuses.

This logical decomposition does not prescribe a framework, database, LLM, or parser library. Deterministic rules and search are permitted. The final documentation must explain the chosen approach and its applicability limits.

## Required user questions

The interface must answer, using active terms and review flags:

1. What delivery date applies to STN-101 on 10 March 2026?
2. What is the amount of STN-102?
3. What is the amount of STN-103?
4. Which contracts schedule delivery before 1 April 2026, and which have unapproved delivery-date changes?

Field selection, filters, buttons, or text queries are acceptable interaction forms.

## Supplied-data acceptance baseline

| Contract | Supplier | Effective amount | Effective delivery date | Review information |
|---|---|---:|---|---|
| STN-101 | ООО «Вектор Прибор» | ₽1,380,000 | 30.04.2026 | Signed amendment `02_amendment_signed.txt` replaces the original ₽1,200,000 and 15.04.2026. Unsigned draft `06_amendment_draft.txt` proposes ₽1,450,000 and 10.05.2026. |
| STN-102 | ООО «Контур Электро» | ₽840,000 | 20.03.2026 | Supplier letter `05_supplier_email.txt` proposes 27.03.2026, but no consent or signed amendment exists. |
| STN-103 | ООО «ПромСнаб Сервис» | `нет данных` | 30.04.2026 | The ₽600,000 internal budget limit is not an agreed contract value. |

For the supplied scenario, only STN-102 has delivery scheduled before 1 April 2026. STN-101 and STN-102 both have unapproved proposed delivery-date changes.

## Scope limits

OCR, PDF/DOCX ingestion, and arbitrary chat are outside the prototype scope. A paid API or subscription must not be required. Generic production and operational behavior remains governed by `docs/CONTRACTS.md`.

## Verification requirements

- Exercise a working multi-file upload-and-review scenario.
- Confirm correct extracted values, exact evidence, missing-value handling, document-status handling, and amendment precedence.
- Confirm that letters and drafts create review information without changing effective values.
- Confirm that changing a source field changes the derived result without code changes.
- Confirm that a new document of the same general format can be processed without filename-specific logic.
- Keep service-specific tests hermetic under the generic testing conventions.

## Delivery documentation requirements

The completed prototype README must include installation and launch commands, dependencies, examples, known limitations, actual time spent, and remaining tasks. It must also contain a short product note covering the target user, five client questions, assumptions, two usefulness/quality metrics, architecture, three key technical trade-offs, scaling and access-control implications, three prioritized improvements, and a concise AI-assisted-development report.

## Evolution considerations

At 100,000 documents and with access permissions, reassess indexing, storage, processing throughput, tenant/role isolation, and source-level authorization. Those mechanisms are not selected in the current prototype phase.

## Implemented processing design

The backend accepts UTF-8 document text in a JSON request from the static browser interface. `back/parser.py` classifies by document content, links explicit contract numbers, and captures totals and delivery dates only from their immediate supported clauses. Payment values and deadlines elsewhere in the same paragraph are not candidates. Multiple distinct supported values remain conflicts requiring review. Signed amendments are ordered by effective date, document date, and upload order rather than filename.

Only signed contracts with one unique contract number contribute effective rows. Negated or unresolved signatures, missing numbers, and duplicate contract numbers remain visible as review items and original documents; their supporting amendments are not applied silently. Invalid source-derived dates produce document-specific warnings instead of rejecting the HTTP batch. Request-level dates remain strictly validated.

Every uploaded document receives a stable one-based ID in upload order. Evidence contains this `document_id`, filename, exact source line, paragraph number, and character offset, so duplicate filenames do not redirect evidence to another document. Static file reads are offloaded with `asyncio.to_thread`; parsing is bounded by request and per-document size limits and runs without external services.

The review response keeps effective contract values, review items, and original documents separate. The frontend renders `нет данных` for null values and provides evidence anchors plus field-specific answers and a delivery-cutoff report. Review items use `delivery_change_status` to distinguish `unapproved`, `approved_pending`, `unresolved`, and `none`; signed future amendments are not reported as unapproved. The parser intentionally targets the supplied general Russian TXT format; ambiguous or unsupported formulations require review rather than inference.

## Service decisions

### 2026-11-06 — Exclude ambiguous contracts and distinguish pending approval

**Status:** Accepted

**Context:** Review found that negated contract signatures and duplicate contract numbers could contribute apparently effective rows, while signed future amendments were grouped with unapproved proposals. Duplicate filenames also made filename-only evidence navigation ambiguous.

**Decision:** Effective rows require a signed contract with one unique number. Duplicate or unresolved base contracts and their supporting documents require review rather than inferred terms. Source-date errors are document warnings, not malformed HTTP. Evidence uses upload-order document IDs, and delivery changes explicitly distinguish unapproved, approved-but-pending, unresolved, and absent states.

**Consequences:** Users see no active terms where contract identity or signature is unreliable. Signed future amendments remain visible without being called unapproved, and every evidence anchor identifies one uploaded document even when basenames repeat. This refines “Treat signed effective amendments as the only source of changed terms” without changing the underlying amendment rule.

### 2026-11-06 — Treat signed effective amendments as the only source of changed terms

**Status:** Accepted

**Context:** The sample set contains a signed amendment, a supplier proposal, and an unsigned draft. The assignment requires reproducible legal-status handling and verifiable evidence.

**Decision:** For the prototype, only amendments signed by both parties and effective at the review date modify active contract terms. Letters and unsigned drafts remain separate review items. Every extracted amount and delivery date retains its file name, exact quote, and paragraph location; absent values are shown as `нет данных` rather than inferred.

**Consequences:** Payment values and budget limits must not become contract totals, and proposed dates must not replace active delivery dates. Ambiguous document links or statuses require human review. This decision records the assignment's product rule, not a general legal interpretation for other domains.

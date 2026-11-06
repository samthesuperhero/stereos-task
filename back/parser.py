from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_REVIEW_DATE = date(2026, 3, 10)
DEFAULT_DELIVERY_CUTOFF = date(2026, 4, 1)
DATE_PATTERN = r"\d{2}\.\d{2}\.\d{4}"
CONTRACT_PATTERN = r"[A-ZА-ЯЁ0-9]+(?:-[A-ZА-ЯЁ0-9]+)+"


@dataclass(frozen=True)
class Upload:
    name: str
    text: str


@dataclass(frozen=True)
class Paragraph:
    number: int
    text: str
    start: int


@dataclass
class Document:
    id: int
    name: str
    text: str
    paragraphs: list[Paragraph]
    kind: str
    status: str
    contract_numbers: list[str]
    document_date: date | None
    effective_date: date | None
    invalid_effective_date: bool
    warnings: list[str]


def _parse_date(value: str) -> date | None:
    try:
        day, month, year = (int(part) for part in value.split("."))
        return date(year, month, day)
    except ValueError:
        return None


def _paragraphs(text: str) -> list[Paragraph]:
    return [
        Paragraph(number=index, text=match.group(), start=match.start())
        for index, match in enumerate(re.finditer(r"[^\r\n]+", text), start=1)
        if match.group().strip()
    ]


def _contract_numbers(text: str, kind: str) -> list[str]:
    if kind == "contract":
        match = re.search(
            rf"ДОГОВОР\s+ПОСТАВКИ\s+№\s*({CONTRACT_PATTERN})", text, re.IGNORECASE
        )
        return [match.group(1).upper()] if match else []
    matches = re.findall(rf"ДОГОВОР[АУ]?\s+({CONTRACT_PATTERN})", text, re.IGNORECASE)
    return list(dict.fromkeys(match.upper() for match in matches))


def classify(upload: Upload, document_id: int) -> Document:
    text = upload.text.replace("\r\n", "\n").replace("\r", "\n")
    upper = text.upper()
    if re.search(r"ДОГОВОР\s+ПОСТАВКИ\s+№", upper):
        kind = "contract"
    elif "ПРОЕКТ" in upper and "ДОПОЛНИТЕЛЬНОГО СОГЛАШЕНИЯ" in upper:
        kind = "draft"
    elif "ПИСЬМО ПОСТАВЩИКА" in upper:
        kind = "letter"
    elif "ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ" in upper:
        kind = "amendment"
    else:
        kind = "unknown"

    signed = bool(re.search(r"подписан[о]?\s+обеими\s+сторонами", text, re.IGNORECASE))
    unsigned = bool(re.search(r"не\s+подписан", text, re.IGNORECASE))
    effective_match = re.search(
        rf"вступает\s+в\s+силу\s+({DATE_PATTERN})", text, re.IGNORECASE
    )
    date_match = re.search(rf"^Дата(?:\s+проекта)?:\s*({DATE_PATTERN})", text, re.IGNORECASE | re.MULTILINE)
    document_date = _parse_date(date_match.group(1)) if date_match else None
    effective_date = _parse_date(effective_match.group(1)) if effective_match else None
    warnings = []
    if date_match and document_date is None:
        warnings.append(f"Некорректная дата документа: {date_match.group(1)}")
    if effective_match and effective_date is None:
        warnings.append(
            f"Некорректная дата вступления в силу: {effective_match.group(1)}"
        )
    if kind in {"contract", "amendment"}:
        status = "signed" if signed and not unsigned else "unresolved"
    elif kind == "draft":
        status = "draft"
    elif kind == "letter":
        status = "proposal"
    else:
        status = "unresolved"
    return Document(
        id=document_id,
        name=Path(upload.name).name,
        text=text,
        paragraphs=_paragraphs(text),
        kind=kind,
        status=status,
        contract_numbers=_contract_numbers(text, kind),
        document_date=document_date,
        effective_date=effective_date,
        invalid_effective_date=bool(effective_match and effective_date is None),
        warnings=warnings,
    )


def _evidence(document: Document, paragraph: Paragraph) -> dict[str, Any]:
    return {
        "document_id": document.id,
        "filename": document.name,
        "quote": paragraph.text,
        "paragraph": paragraph.number,
        "start": paragraph.start,
    }


def _supplier(document: Document) -> dict[str, Any] | None:
    for paragraph in document.paragraphs:
        match = re.search(r"Поставщик:\s*(.+?)(?:\.\s*$|$)", paragraph.text, re.IGNORECASE)
        if match:
            return {
                "value": match.group(1).strip(),
                "evidence": _evidence(document, paragraph),
            }
    return None


def _amount_candidates(document: Document) -> list[tuple[int, dict[str, Any]]]:
    candidates = []
    number = r"(\d(?:[\d \u00a0\u202f]*\d)?)"
    pattern = re.compile(
        r"(?:общая\s+стоимость(?:\s+поставки)?\s+составляет|"
        r"изменить\s+общую\s+стоимость(?:\s+поставки)?(?:\s+на)?)"
        + rf"\s*{number}\s*(?:\([^)]*\)\s*)?рубл",
        re.IGNORECASE,
    )
    for paragraph in document.paragraphs:
        for match in pattern.finditer(paragraph.text):
            value = int(re.sub(r"\D", "", match.group(1)))
            candidates.append((value, _evidence(document, paragraph)))
    return candidates


def _date_candidates(
    document: Document,
) -> tuple[list[tuple[date, dict[str, Any]]], list[str]]:
    candidates = []
    warnings = []
    patterns = (
        rf"поставить[^.\r\n]*?не\s+позднее\s+({DATE_PATTERN})",
        rf"срок\s+поставки[^.\r\n]*?не\s+позднее\s+({DATE_PATTERN})",
        rf"(?:перенести|изменить)\s+срок\s+поставки(?:\s+с\s+{DATE_PATTERN})?\s+на\s+({DATE_PATTERN})",
    )
    for paragraph in document.paragraphs:
        for pattern in patterns:
            for match in re.finditer(pattern, paragraph.text, re.IGNORECASE):
                value = match.group(1)
                parsed = _parse_date(value)
                if parsed is None:
                    warning = f"Некорректная дата поставки: {value}"
                    if warning not in warnings:
                        warnings.append(warning)
                    continue
                candidates.append((parsed, _evidence(document, paragraph)))
    return candidates, warnings


def _single_candidate(
    document: Document,
    candidates: list[tuple[Any, dict[str, Any]]],
    field: str,
) -> tuple[Any, str | None]:
    distinct = list(dict.fromkeys(value for value, _ in candidates))
    if not distinct:
        return None, None
    if len(distinct) > 1:
        return None, f"Противоречивые значения в {document.name}: {field}"
    value = next(value for value, _ in candidates if value == distinct[0])
    evidence = next(evidence for value, evidence in candidates if value == distinct[0])
    return {"value": value, "evidence": evidence}, None


def _public_value(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    value = candidate["value"]
    return {
        "value": value.isoformat() if isinstance(value, date) else value,
        "evidence": candidate["evidence"],
    }


def _document_payload(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "filename": document.name,
        "kind": document.kind,
        "status": document.status,
        "contract_numbers": document.contract_numbers,
        "paragraphs": [
            {"number": paragraph.number, "text": paragraph.text}
            for paragraph in document.paragraphs
        ],
    }


def analyze(uploads: list[Upload], review_date: date) -> dict[str, Any]:
    documents = [classify(upload, index) for index, upload in enumerate(uploads, start=1)]
    contracts = [document for document in documents if document.kind == "contract"]
    contracts_by_number: dict[str, list[Document]] = {}
    for contract in contracts:
        if len(contract.contract_numbers) == 1:
            number = contract.contract_numbers[0]
            contracts_by_number.setdefault(number, []).append(contract)
    active_numbers = {
        number
        for number, numbered_contracts in contracts_by_number.items()
        if len(numbered_contracts) == 1 and numbered_contracts[0].status == "signed"
    }
    linked: dict[str, list[Document]] = {number: [] for number in active_numbers}
    review_items = []

    for document in documents:
        if document.kind == "contract":
            number = (
                document.contract_numbers[0]
                if len(document.contract_numbers) == 1
                else None
            )
            if number is None or number not in active_numbers:
                if number is None:
                    reason = "Проверьте номер договора"
                elif len(contracts_by_number[number]) > 1:
                    reason = "Несколько договоров имеют одинаковый номер"
                else:
                    reason = "Договор не подписан обеими сторонами"
                if document.warnings:
                    reason = "; ".join([reason, *document.warnings])
                review_items.append({
                    "filename": document.name,
                    "contract_number": number,
                    "reason": reason,
                    "amount": None,
                    "delivery_date": None,
                    "delivery_change_status": "none",
                })
            continue

        numbers = document.contract_numbers
        number = numbers[0] if len(numbers) == 1 else None
        resolved = number in active_numbers
        if resolved:
            linked[number].append(document)

        amount, amount_warning = _single_candidate(
            document, _amount_candidates(document), "сумма"
        )
        date_candidates, date_warnings = _date_candidates(document)
        delivery, date_warning = _single_candidate(
            document, date_candidates, "срок поставки"
        )
        effective = (
            document.kind == "amendment"
            and document.status == "signed"
            and document.effective_date is not None
            and document.effective_date <= review_date
        )
        if effective and resolved:
            continue

        if not resolved:
            delivery_change_status = "unresolved"
            if number in contracts_by_number:
                reason = "Договор требует проверки; изменения не применены"
            else:
                reason = "Не удалось однозначно связать документ с договором"
        elif document.kind == "unknown":
            delivery_change_status = "unresolved"
            reason = "Не удалось определить тип документа"
        elif document.kind == "amendment" and document.status != "signed":
            delivery_change_status = "unapproved"
            reason = "Дополнительное соглашение не подписано обеими сторонами"
        elif document.kind == "amendment" and document.effective_date is None:
            delivery_change_status = "unresolved"
            if document.invalid_effective_date:
                reason = "Некорректная дата вступления дополнительного соглашения в силу"
            else:
                reason = "Не указана дата вступления дополнительного соглашения в силу"
        elif document.kind == "amendment":
            delivery_change_status = "approved_pending"
            reason = "Дополнительное соглашение ещё не вступило в силу"
        elif document.kind == "draft":
            delivery_change_status = "unapproved"
            reason = "Несогласованный проект изменения"
        else:
            delivery_change_status = "unapproved"
            reason = "Предложение поставщика не изменяет условия договора"
        warnings = [*document.warnings, *date_warnings]
        warnings.extend(
            warning for warning in (amount_warning, date_warning) if warning
        )
        if warnings:
            reason = "; ".join([reason, *dict.fromkeys(warnings)])
        review_items.append({
            "filename": document.name,
            "contract_number": number,
            "reason": reason,
            "amount": _public_value(amount),
            "delivery_date": _public_value(delivery),
            "delivery_change_status": delivery_change_status,
        })

    rows = []
    for contract in contracts:
        if len(contract.contract_numbers) != 1:
            continue
        number = contract.contract_numbers[0]
        if number not in active_numbers:
            continue
        warnings = list(contract.warnings)
        amount, warning = _single_candidate(
            contract, _amount_candidates(contract), "сумма"
        )
        if warning:
            warnings.append(warning)
        date_candidates, date_warnings = _date_candidates(contract)
        warnings.extend(date_warnings)
        delivery, warning = _single_candidate(
            contract, date_candidates, "срок поставки"
        )
        if warning:
            warnings.append(warning)
        supplier = _supplier(contract)
        amendments = [
            document
            for document in linked.get(number, [])
            if document.kind == "amendment"
            and document.status == "signed"
            and document.effective_date is not None
            and document.effective_date <= review_date
        ]
        amendments.sort(
            key=lambda document: (
                document.effective_date or date.min,
                document.document_date or date.min,
                document.id,
            )
        )
        for amendment in amendments:
            warnings.extend(amendment.warnings)
            new_amount, warning = _single_candidate(
                amendment, _amount_candidates(amendment), "сумма"
            )
            if warning:
                warnings.append(warning)
            elif new_amount is not None:
                amount = new_amount
            date_candidates, date_warnings = _date_candidates(amendment)
            warnings.extend(date_warnings)
            new_delivery, warning = _single_candidate(
                amendment, date_candidates, "срок поставки"
            )
            if warning:
                warnings.append(warning)
            elif new_delivery is not None:
                delivery = new_delivery
        rows.append({
            "number": number,
            "supplier": supplier,
            "amount": _public_value(amount),
            "delivery_date": _public_value(delivery),
            "review_flags": list(dict.fromkeys(warnings)),
        })

    return {
        "review_date": review_date.isoformat(),
        "contracts": rows,
        "review_items": review_items,
        "documents": [_document_payload(document) for document in documents],
    }


def delivery_report(result: dict[str, Any], cutoff: date) -> dict[str, Any]:
    before = []
    proposed = []
    for contract in result["contracts"]:
        delivery = contract["delivery_date"]
        if delivery and date.fromisoformat(delivery["value"]) < cutoff:
            before.append(contract["number"])
    for item in result["review_items"]:
        if (
            item["contract_number"]
            and item["delivery_date"]
            and item["delivery_change_status"] == "unapproved"
        ):
            proposed.append(item["contract_number"])
    return {
        "cutoff": cutoff.isoformat(),
        "delivery_before": sorted(set(before)),
        "unapproved_delivery_changes": sorted(set(proposed)),
    }

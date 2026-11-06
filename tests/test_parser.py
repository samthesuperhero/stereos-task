from datetime import date

from back.parser import DEFAULT_REVIEW_DATE, Upload, analyze, delivery_report


def by_number(result, number):
    return next(row for row in result["contracts"] if row["number"] == number)


def test_supplied_documents_have_verifiable_effective_terms(uploads):
    result = analyze(uploads, DEFAULT_REVIEW_DATE)

    first = by_number(result, "STN-101")
    assert first["supplier"]["value"] == "ООО «Вектор Прибор»"
    assert first["amount"]["value"] == 1_380_000
    assert first["amount"]["evidence"]["filename"] == "02_amendment_signed.txt"
    assert first["delivery_date"]["value"] == "2026-04-30"
    assert first["delivery_date"]["evidence"]["quote"].endswith("30.04.2026».")

    second = by_number(result, "STN-102")
    assert second["amount"]["value"] == 840_000
    assert second["delivery_date"]["value"] == "2026-03-20"

    third = by_number(result, "STN-103")
    assert third["amount"] is None
    assert third["delivery_date"]["value"] == "2026-04-30"

    report = delivery_report(result, date(2026, 4, 1))
    assert report["delivery_before"] == ["STN-102"]
    assert report["unapproved_delivery_changes"] == ["STN-101", "STN-102"]


def test_proposals_are_visible_but_do_not_replace_terms(uploads):
    result = analyze(uploads, DEFAULT_REVIEW_DATE)
    items = {item["filename"]: item for item in result["review_items"]}

    letter = items["05_supplier_email.txt"]
    assert letter["delivery_date"]["value"] == "2026-03-27"
    assert letter["reason"] == "Предложение поставщика не изменяет условия договора"
    draft = items["06_amendment_draft.txt"]
    assert draft["amount"]["value"] == 1_450_000
    assert draft["delivery_date"]["value"] == "2026-05-10"


def test_every_effective_value_has_an_exact_source_quote(uploads):
    source = {upload.name: upload.text for upload in uploads}
    result = analyze(uploads, DEFAULT_REVIEW_DATE)
    for contract in result["contracts"]:
        for field in ("supplier", "amount", "delivery_date"):
            value = contract[field]
            if value is None:
                continue
            evidence = value["evidence"]
            assert evidence["quote"] in source[evidence["filename"]]
            document = next(item for item in result["documents"] if item["filename"] == evidence["filename"])
            paragraph = next(item for item in document["paragraphs"] if item["number"] == evidence["paragraph"])
            assert paragraph["text"] == evidence["quote"]


def test_source_edit_and_new_contract_do_not_need_code_changes(uploads):
    changed = [
        Upload(upload.name, upload.text.replace("840 000", "900 000"))
        for upload in uploads
    ]
    changed.append(Upload("arbitrary-name.txt", """ДОГОВОР ПОСТАВКИ № NEW-7
Дата: 01.03.2026
Статус: подписан обеими сторонами 01.03.2026.
Поставщик: ООО «Новый».
Общая стоимость поставки составляет 95 000 рублей.
Поставщик обязуется поставить товар не позднее 25.03.2026.
"""))

    result = analyze(changed, DEFAULT_REVIEW_DATE)
    assert by_number(result, "STN-102")["amount"]["value"] == 900_000
    new = by_number(result, "NEW-7")
    assert new["amount"]["value"] == 95_000
    assert new["delivery_date"]["value"] == "2026-03-25"


def test_future_amendment_does_not_apply_before_effective_date(uploads):
    result = analyze(uploads, date(2026, 2, 28))
    first = by_number(result, "STN-101")
    assert first["amount"]["value"] == 1_200_000
    assert first["delivery_date"]["value"] == "2026-04-15"
    assert any(item["filename"] == "02_amendment_signed.txt" for item in result["review_items"])


def test_ambiguous_supporting_document_requires_review(uploads):
    ambiguous = Upload("note.txt", """ПИСЬМО ПОСТАВЩИКА
Тема: договоры STN-101 и STN-102
По договору STN-101 и договору STN-102 предлагаем изменить срок поставки на 01.05.2026.
""")
    result = analyze([*uploads, ambiguous], DEFAULT_REVIEW_DATE)
    item = next(item for item in result["review_items"] if item["filename"] == "note.txt")
    assert item["contract_number"] is None
    assert "однозначно связать" in item["reason"]
    assert by_number(result, "STN-101")["delivery_date"]["value"] == "2026-04-30"


def make_contract(
    number="STN-200",
    status="подписан обеими сторонами",
    amount="Общая стоимость поставки составляет 840 000 рублей.",
    delivery="Поставщик обязуется поставить товар не позднее 20.03.2026.",
    document_date="10.02.2026",
):
    return f"""ДОГОВОР ПОСТАВКИ № {number}
Дата: {document_date}
Статус: {status}.
Поставщик: ООО «Тест».
{amount}
{delivery}
"""


def test_unsigned_contract_requires_review_and_has_no_effective_row():
    result = analyze([
        Upload("unsigned.txt", make_contract(status="не подписан обеими сторонами"))
    ], DEFAULT_REVIEW_DATE)

    assert result["contracts"] == []
    assert result["documents"][0]["status"] == "unresolved"
    item = result["review_items"][0]
    assert item["contract_number"] == "STN-200"
    assert "не подписан" in item["reason"]
    assert item["delivery_change_status"] == "none"


def test_duplicate_contract_numbers_and_their_amendments_require_review():
    amendment = """ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1 К ДОГОВОРУ STN-200
Дата: 01.03.2026
Статус: подписано обеими сторонами.
Общая стоимость поставки составляет 900 000 рублей.
Вступает в силу 01.03.2026.
"""
    result = analyze([
        Upload("first.txt", make_contract()),
        Upload("second.txt", make_contract(amount="Общая стоимость поставки составляет 950 000 рублей.")),
        Upload("amendment.txt", amendment),
    ], DEFAULT_REVIEW_DATE)

    assert result["contracts"] == []
    assert len(result["review_items"]) == 3
    assert all("одинаковый номер" in item["reason"] for item in result["review_items"][:2])
    assert "изменения не применены" in result["review_items"][2]["reason"]


def test_same_line_payment_values_do_not_replace_contract_terms():
    result = analyze([
        Upload("context.txt", make_contract(
            amount="Авансовый платеж 252 000 рублей. Общая стоимость поставки составляет 840 000 рублей.",
            delivery="Оплата не позднее 10.04.2026. Срок поставки — не позднее 20.03.2026.",
        ))
    ], DEFAULT_REVIEW_DATE)

    contract = by_number(result, "STN-200")
    assert contract["amount"]["value"] == 840_000
    assert contract["delivery_date"]["value"] == "2026-03-20"
    assert contract["review_flags"] == []


def test_multiple_distinct_same_line_values_remain_conflicts():
    result = analyze([
        Upload("conflict.txt", make_contract(
            amount="Общая стоимость поставки составляет 840 000 рублей. Общая стоимость поставки составляет 850 000 рублей.",
            delivery="Поставщик обязуется поставить товар не позднее 20.03.2026. Срок поставки — не позднее 21.03.2026.",
        ))
    ], DEFAULT_REVIEW_DATE)

    contract = by_number(result, "STN-200")
    assert contract["amount"] is None
    assert contract["delivery_date"] is None
    assert len(contract["review_flags"]) == 2


def test_invalid_source_dates_become_review_warnings():
    result = analyze([
        Upload("dates.txt", make_contract(
            document_date="31.02.2026",
            delivery="Поставщик обязуется поставить товар не позднее 32.03.2026.",
        ))
    ], DEFAULT_REVIEW_DATE)

    contract = by_number(result, "STN-200")
    assert contract["amount"]["value"] == 840_000
    assert contract["delivery_date"] is None
    assert "Некорректная дата документа: 31.02.2026" in contract["review_flags"]
    assert "Некорректная дата поставки: 32.03.2026" in contract["review_flags"]


def test_invalid_amendment_effective_date_does_not_abort_batch():
    amendment = """ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1 К ДОГОВОРУ STN-200
Дата: 01.03.2026
Статус: подписано обеими сторонами.
Поставщик обязуется поставить товар не позднее 30.04.2026.
Вступает в силу 31.02.2026.
"""
    result = analyze([
        Upload("contract.txt", make_contract()),
        Upload("amendment.txt", amendment),
    ], DEFAULT_REVIEW_DATE)

    assert by_number(result, "STN-200")["delivery_date"]["value"] == "2026-03-20"
    item = result["review_items"][0]
    assert "Некорректная дата вступления" in item["reason"]
    assert item["delivery_change_status"] == "unresolved"
    assert delivery_report(result, date(2026, 5, 1))["unapproved_delivery_changes"] == []


def test_future_signed_amendment_is_not_an_unapproved_change():
    amendment = """ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1 К ДОГОВОРУ STN-200
Дата: 01.03.2026
Статус: подписано обеими сторонами.
Поставщик обязуется поставить товар не позднее 30.04.2026.
Вступает в силу 01.04.2026.
"""
    result = analyze([
        Upload("contract.txt", make_contract()),
        Upload("future.txt", amendment),
    ], DEFAULT_REVIEW_DATE)

    item = result["review_items"][0]
    assert item["delivery_change_status"] == "approved_pending"
    assert delivery_report(result, date(2026, 5, 1))["unapproved_delivery_changes"] == []
    assert by_number(result, "STN-200")["delivery_date"]["value"] == "2026-03-20"


def test_duplicate_filenames_use_document_ids_in_evidence():
    result = analyze([
        Upload("same.txt", make_contract(number="STN-200")),
        Upload("same.txt", make_contract(number="STN-201")),
    ], DEFAULT_REVIEW_DATE)

    assert [document["id"] for document in result["documents"]] == [1, 2]
    first = by_number(result, "STN-200")["amount"]["evidence"]
    second = by_number(result, "STN-201")["amount"]["evidence"]
    assert first["filename"] == second["filename"] == "same.txt"
    assert first["document_id"] == 1
    assert second["document_id"] == 2
    for evidence in (first, second):
        document = next(item for item in result["documents"] if item["id"] == evidence["document_id"])
        paragraph = next(item for item in document["paragraphs"] if item["number"] == evidence["paragraph"])
        assert paragraph["text"] == evidence["quote"]

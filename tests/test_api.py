import json

from back.config import Settings
from back.http import Application


async def test_health_and_configuration(tmp_path):
    application = Application(Settings(static_dir=tmp_path))
    health = await application.handle("GET", "/api/health", {}, b"")
    config = await application.handle("GET", "/api/config", {}, b"")
    assert health.status == 200
    assert json.loads(health.body) == {"status": "ok"}
    assert json.loads(config.body)["review_date"] == "2026-03-10"


async def test_review_api_processes_multiple_documents(uploads, tmp_path):
    application = Application(Settings(static_dir=tmp_path))
    body = json.dumps({
        "documents": [{"name": upload.name, "text": upload.text} for upload in uploads]
    }).encode()
    response = await application.handle("POST", "/api/review", {}, body)
    payload = json.loads(response.body)
    assert response.status == 200
    assert len(payload["contracts"]) == 3
    assert payload["delivery_report"]["delivery_before"] == ["STN-102"]


async def test_review_api_rejects_bad_json(tmp_path):
    application = Application(Settings(static_dir=tmp_path))
    response = await application.handle("POST", "/api/review", {}, b"{")
    assert response.status == 400
    assert set(json.loads(response.body)) == {"error"}


async def test_static_frontend_is_served_and_traversal_is_blocked(tmp_path):
    (tmp_path / "index.html").write_text("prototype", encoding="utf-8")
    application = Application(Settings(static_dir=tmp_path))
    response = await application.handle("GET", "/", {}, b"")
    assert response.status == 200
    assert response.body == b"prototype"
    missing = await application.handle("GET", "/missing", {}, b"")
    assert missing.status == 404


async def test_invalid_source_date_is_a_review_warning_not_bad_http(tmp_path):
    application = Application(Settings(static_dir=tmp_path))
    document = """ДОГОВОР ПОСТАВКИ № STN-200
Дата: 31.02.2026
Статус: подписан обеими сторонами.
Поставщик: ООО «Тест».
Общая стоимость поставки составляет 840 000 рублей.
Поставщик обязуется поставить товар не позднее 20.03.2026.
"""
    body = json.dumps({
        "documents": [{"name": "contract.txt", "text": document}]
    }).encode()

    response = await application.handle("POST", "/api/review", {}, body)
    payload = json.loads(response.body)
    assert response.status == 200
    assert payload["contracts"][0]["amount"]["value"] == 840_000
    assert "Некорректная дата документа: 31.02.2026" in payload["contracts"][0]["review_flags"]

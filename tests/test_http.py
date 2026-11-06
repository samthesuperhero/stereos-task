import asyncio
import json

from back.config import Settings
from back.http import Application, HttpServer


async def request(port, payload):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    body = json.dumps(payload).encode()
    writer.write(
        b"POST /api/review HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


async def test_real_http_upload_and_bounded_shutdown(uploads, tmp_path):
    settings = Settings(host="127.0.0.1", port=0, static_dir=tmp_path)
    server = HttpServer(Application(settings), settings)
    await server.start()
    port = server.server.sockets[0].getsockname()[1]
    try:
        response = await request(port, {
            "documents": [{"name": upload.name, "text": upload.text} for upload in uploads]
        })
        header, body = response.split(b"\r\n\r\n", 1)
        assert b"200 OK" in header
        assert len(json.loads(body)["contracts"]) == 3
    finally:
        await server.close()
    assert server.server.is_serving() is False


async def raw_request(port, method, path):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


def response_parts(response):
    header, body = response.split(b"\r\n\r\n", 1)
    headers = {}
    for line in header.split(b"\r\n")[1:]:
        name, value = line.split(b":", 1)
        headers[name.lower()] = value.strip()
    return header, headers, body


async def test_head_preserves_get_length_and_never_sends_a_body(tmp_path):
    (tmp_path / "index.html").write_text("prototype", encoding="utf-8")
    settings = Settings(host="127.0.0.1", port=0, static_dir=tmp_path)
    server = HttpServer(Application(settings), settings)
    await server.start()
    port = server.server.sockets[0].getsockname()[1]
    try:
        get_root = await raw_request(port, "GET", "/")
        head_root = await raw_request(port, "HEAD", "/")
        get_missing = await raw_request(port, "GET", "/missing")
        head_missing = await raw_request(port, "HEAD", "/missing")
        get_health = await raw_request(port, "GET", "/api/health")
        head_health = await raw_request(port, "HEAD", "/api/health")
    finally:
        await server.close()

    for get_response, head_response in (
        (get_root, head_root),
        (get_missing, head_missing),
        (get_health, head_health),
    ):
        get_header, _get_headers, get_body = response_parts(get_response)
        head_header, head_headers, head_body = response_parts(head_response)
        assert get_header.split(b"\r\n", 1)[0].split(b" ", 2)[1] == head_header.split(b"\r\n", 1)[0].split(b" ", 2)[1]
        assert int(head_headers[b"content-length"]) == len(get_body)
        assert head_body == b""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import socket
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from typing import Any
from urllib.parse import unquote, urlsplit

from back.config import Settings
from back.errors import ApiError, error_payload
from back.parser import (
    DEFAULT_DELIVERY_CUTOFF,
    DEFAULT_REVIEW_DATE,
    Upload,
    analyze,
    delivery_report,
)

logger = logging.getLogger(__name__)


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"

    @classmethod
    def json(cls, status: int, payload: Any) -> Response:
        return cls(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class Application:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def handle(
        self, method: str, target: str, headers: dict[str, str], body: bytes
    ) -> Response:
        try:
            return await self._dispatch(method, target, headers, body)
        except ApiError as exc:
            return Response.json(
                exc.status, error_payload(exc.code, exc.message, exc.details)
            )

    async def _dispatch(
        self, method: str, target: str, headers: dict[str, str], body: bytes
    ) -> Response:
        path = urlsplit(target).path
        if path == "/api/health" and method in {"GET", "HEAD"}:
            return Response.json(200, {"status": "ok"})
        if path == "/api/config" and method in {"GET", "HEAD"}:
            return Response.json(200, {
                "review_date": DEFAULT_REVIEW_DATE.isoformat(),
                "delivery_cutoff": DEFAULT_DELIVERY_CUTOFF.isoformat(),
            })
        if path == "/api/review" and method == "POST":
            return await self._review(body)
        if path.startswith("/api/"):
            raise ApiError(404, "not_found", "API endpoint not found")
        if method not in {"GET", "HEAD"}:
            raise ApiError(405, "method_not_allowed", "Method not allowed")
        return await self._static(path)

    async def _review(self, body: bytes) -> Response:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "invalid_json", "Request body must be UTF-8 JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
            raise ApiError(400, "invalid_request", "documents must be an array")
        if not 1 <= len(payload["documents"]) <= 100:
            raise ApiError(400, "invalid_request", "Upload between 1 and 100 documents")
        try:
            review_date = date.fromisoformat(
                payload.get("review_date", DEFAULT_REVIEW_DATE.isoformat())
            )
            cutoff = date.fromisoformat(
                payload.get("delivery_cutoff", DEFAULT_DELIVERY_CUTOFF.isoformat())
            )
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "invalid_date", "Dates must use YYYY-MM-DD") from exc

        uploads = []
        for item in payload["documents"]:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ApiError(400, "invalid_document", "Each document needs name and text")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ApiError(400, "invalid_document", "Each document needs name and text")
            if len(item["text"].encode("utf-8")) > 2 * 1024 * 1024:
                raise ApiError(413, "document_too_large", "Each TXT file must be at most 2 MiB")
            uploads.append(Upload(name=name, text=item["text"]))
        result = analyze(uploads, review_date)
        result["delivery_report"] = delivery_report(result, cutoff)
        return Response.json(200, result)

    async def _static(self, path: str) -> Response:
        relative = unquote(path).lstrip("/") or "index.html"
        root = self.settings.static_dir.resolve()
        candidate = (root / relative).resolve()
        if root != candidate and root not in candidate.parents:
            raise ApiError(404, "not_found", "File not found")
        try:
            content = await asyncio.to_thread(candidate.read_bytes)
        except (FileNotFoundError, IsADirectoryError, OSError) as exc:
            raise ApiError(404, "not_found", "File not found") from exc
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        return Response(200, content, content_type)


class HttpServer:
    def __init__(self, application: Application, settings: Settings) -> None:
        self.application = application
        self.settings = settings
        self.server: asyncio.AbstractServer | None = None
        self.handlers: set[asyncio.Task] = set()

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_client,
            self.settings.host,
            self.settings.port,
            limit=65536,
        )

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        handlers = [task for task in self.handlers if task is not asyncio.current_task()]
        if handlers:
            _, pending = await asyncio.wait(
                handlers, timeout=self.settings.shutdown_timeout_seconds
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        for task in self.handlers:
            if task is not asyncio.current_task() and not task.done():
                task.cancel()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self.handlers.add(task)
        try:
            await asyncio.wait_for(
                self._respond(reader, writer), self.settings.request_timeout_seconds
            )
        except (TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception:
            logger.exception("HTTP connection failed")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if task is not None:
                self.handlers.discard(task)

    async def _respond(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        status = 200
        method = ""
        try:
            header_block = await reader.readuntil(b"\r\n\r\n")
            lines = header_block.decode("ascii").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if not line:
                    continue
                name, value = line.split(":", 1)
                headers[name.lower()] = value.strip()
            if "transfer-encoding" in headers:
                raise ApiError(400, "invalid_request", "Transfer encoding is not supported")
            length = int(headers.get("content-length", "0"))
            if length < 0:
                raise ValueError("Negative content length")
            if length > self.settings.max_request_bytes:
                raise ApiError(413, "request_too_large", "Request body is too large")
            body = await reader.readexactly(length) if length else b""
            response = await self.application.handle(method, target, headers, body)
            status = response.status
        except ApiError as exc:
            status = exc.status
            response = Response.json(
                status, error_payload(exc.code, exc.message, exc.details)
            )
        except (ValueError, UnicodeError, asyncio.LimitOverrunError):
            status = 400
            response = Response.json(
                status, error_payload("bad_request", "Malformed HTTP request")
            )
        except Exception:
            logger.exception("Request failed")
            status = 500
            response = Response.json(
                status, error_payload("internal_error", "Internal server error")
            )
        phrase = HTTPStatus(status).phrase
        writer.write(
            f"HTTP/1.1 {status} {phrase}\r\n"
            f"Content-Type: {response.content_type}\r\n"
            f"Content-Length: {len(response.body)}\r\n"
            "X-Content-Type-Options: nosniff\r\n"
            "Connection: close\r\n\r\n".encode("ascii")
        )
        if method != "HEAD":
            writer.write(response.body)
        await writer.drain()


async def sd_notify(message: str) -> None:
    address = __import__("os").environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if not hasattr(socket, "AF_UNIX"):
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        await asyncio.get_running_loop().sock_sendto(sock, message.encode(), address)
    except OSError:
        logger.warning("Could not notify systemd", extra={"structured": {}})
    finally:
        sock.close()

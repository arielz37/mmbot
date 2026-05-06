from __future__ import annotations

import json
import mimetypes
import uuid
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .chat import answer_question
from .config import (
    PUBLIC_DIR,
    embedding_configured,
    get_embedding_base_url,
    get_embedding_model,
    get_host,
    get_model_base_url,
    get_model_name,
    get_port,
    model_configured,
)
from .db import initialize_db
from .repository import (
    create_entity,
    delete_entity,
    get_entity,
    list_chat_logs,
    list_entities,
    list_published_faq_entries,
    list_unmatched_questions,
    publish_entity,
    seed_demo_data,
    update_entity,
)


class AppHandler(BaseHTTPRequestHandler):
    public_dir = PUBLIC_DIR

    def log_message(self, fmt: str, *args) -> None:
        return

    def send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        content = file_path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(file_path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/health":
                return self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "model_configured": model_configured(),
                        "model_base_url": get_model_base_url() or None,
                        "model_name": get_model_name() or None,
                        "embedding_configured": embedding_configured(),
                        "embedding_base_url": get_embedding_base_url() or None,
                        "embedding_model": get_embedding_model() or None,
                        "api_mode": True,
                    },
                )

            if path == "/faq":
                return self.send_json(HTTPStatus.OK, {"items": list_published_faq_entries()})

            if path == "/admin/entities":
                return self.send_json(
                    HTTPStatus.OK,
                    {
                        "items": list_entities(
                            entity_type=(query.get("entity_type") or [None])[0],
                            status=(query.get("status") or [None])[0],
                        )
                    },
                )

            if path.startswith("/admin/entities/"):
                entity_id = path.removeprefix("/admin/entities/")
                if entity_id.isdigit():
                    entity = get_entity(int(entity_id))
                    if entity is None:
                        return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                    return self.send_json(HTTPStatus.OK, entity)

            if path == "/admin/chat-logs":
                return self.send_json(HTTPStatus.OK, {"items": list_chat_logs()})

            if path == "/admin/unmatched-questions":
                return self.send_json(HTTPStatus.OK, {"items": list_unmatched_questions()})

            if path == "/":
                return self.send_file(self.public_dir / "index.html")
            if path == "/admin":
                return self.send_file(self.public_dir / "admin.html")

            static_file = (self.public_dir / path.lstrip("/")).resolve()
            if self.public_dir in static_file.parents and static_file.exists():
                return self.send_file(static_file)

            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except Exception as exc:
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self.read_json_body()
            if path == "/chat":
                question = body.get("question")
                if not question:
                    return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "question is required"})
                result = answer_question(question=question, session_id=body.get("session_id") or str(uuid.uuid4()))
                return self.send_json(HTTPStatus.OK, result)

            if path == "/admin/entities":
                entity = create_entity(body)
                return self.send_json(HTTPStatus.CREATED, entity)

            if path.endswith("/publish") and path.startswith("/admin/entities/"):
                entity_id = path.removeprefix("/admin/entities/").removesuffix("/publish")
                if entity_id.isdigit():
                    entity = publish_entity(int(entity_id), body.get("updated_by", "admin"))
                    return self.send_json(HTTPStatus.OK, entity)

            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except ValueError as exc:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/admin/entities/"):
                entity_id = path.removeprefix("/admin/entities/")
                if entity_id.isdigit():
                    entity = update_entity(int(entity_id), self.read_json_body())
                    return self.send_json(HTTPStatus.OK, entity)
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except ValueError as exc:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/admin/entities/"):
                entity_id = path.removeprefix("/admin/entities/")
                if entity_id.isdigit():
                    deleted = delete_entity(int(entity_id))
                    if not deleted:
                        return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                    return self.send_json(HTTPStatus.OK, {"ok": True})
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except Exception as exc:
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def run() -> None:
    initialize_db()
    seed_demo_data()
    server = ThreadingHTTPServer((get_host(), get_port()), partial(AppHandler))
    print(f"Club bot server running at http://{get_host()}:{get_port()}")
    server.serve_forever()


if __name__ == "__main__":
    run()

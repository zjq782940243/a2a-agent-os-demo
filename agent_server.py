"""Reusable HTTP primitives for the research and summary agents."""

from __future__ import annotations

import threading
import time
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from common import TaskStore, new_id, now_iso, read_json, write_json, extract_message_text


FINAL_STATES = {"completed", "failed", "canceled"}


class AgentHandler(BaseHTTPRequestHandler):
    agent = None

    def log_message(self, fmt, *args):
        # Keep demo output readable; callers can inspect task history in the UI.
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/.well-known/agent-card.json":
            return write_json(self, self.agent.card)
        if path.startswith("/a2a/tasks/"):
            task_id = path.rsplit("/", 1)[-1]
            if not self.agent.store.has(task_id):
                return write_json(self, {"error": "task_not_found"}, 404)
            return write_json(self, {"task": self.agent.store.snapshot(task_id)})
        if path == "/health":
            return write_json(self, {"ok": True, "agent": self.agent.card["name"]})
        return write_json(self, {"error": "not_found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/a2a/tasks/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            if not self.agent.store.has(task_id):
                return write_json(self, {"error": "task_not_found"}, 404)
            return write_json(self, {"task": self.agent.store.cancel(task_id)}, 200)
        if path != "/a2a":
            return write_json(self, {"error": "not_found"}, 404)
        try:
            payload = read_json(self)
            if payload.get("method") != "message/send":
                return write_json(self, {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32601, "message": "Only message/send is supported"}}, 400)
            params = payload.get("params") or {}
            task_id = new_id(self.agent.slug)
            self.agent.store.create(task_id)
            threading.Thread(target=self.agent.process, args=(task_id, params), daemon=True).start()
            response = {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"task": self.agent.store.snapshot(task_id)}}
            return write_json(self, response, 201)
        except Exception as exc:
            return write_json(self, {"error": "invalid_request", "detail": str(exc)}, 400)


class BaseAgent:
    slug = "agent"

    def __init__(self, port: int, card: dict):
        self.port = port
        self.card = card
        self.store = TaskStore()

    def process(self, task_id: str, params: dict) -> None:
        raise NotImplementedError

    def serve(self) -> ThreadingHTTPServer:
        agent = self
        class Handler(AgentHandler):
            pass
        Handler.agent = agent
        server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        return server

    def run(self) -> None:
        self.serve().serve_forever()


def run_server_in_thread(agent: BaseAgent) -> tuple:
    server = agent.serve()
    thread = threading.Thread(target=server.serve_forever, name=agent.slug, daemon=True)
    thread.start()
    return server, thread


def pause_for_demo(seconds: float = 0.35) -> None:
    # Makes state transitions visible in the browser during a live demo.
    try:
        seconds = float(os.environ.get("A2A_DEMO_PAUSE_SECONDS", seconds))
    except ValueError:
        pass
    time.sleep(max(0.0, seconds))

"""Small persistent memory adapter used to demonstrate UniPi-style memory."""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List

from common import new_id, now_iso


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(__import__("os").environ.get("A2A_MEMORY_DB", str(ROOT / "data" / "runtime" / "memory.db")))


class MemoryStore:
    """SQLite-backed topic memory; intentionally small and inspectable."""

    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, topic TEXT NOT NULL UNIQUE, summary TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        self._db.commit()

    @staticmethod
    def _terms(query: str) -> List[str]:
        return [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if len(term) > 1]

    def search(self, query: str, limit: int = 3) -> List[Dict[str, str]]:
        terms = self._terms(query)
        with self._lock:
            rows = self._db.execute("SELECT id, topic, summary, updated_at FROM memories ORDER BY updated_at DESC").fetchall()
        scored = []
        for row in rows:
            haystack = f"{row['topic']} {row['summary']}".lower()
            score = sum(haystack.count(term) for term in terms) if terms else 0
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["updated_at"]))
        return [{"id": row["id"], "topic": row["topic"], "summary": row["summary"], "updatedAt": row["updated_at"], "score": score} for score, row in scored[:limit]]

    def store(self, topic: str, summary: str) -> Dict[str, str]:
        memory_id = new_id("memory")
        timestamp = now_iso()
        # Keep the demo memory useful without allowing one report to grow forever.
        compact = summary.strip()[:4000]
        with self._lock:
            self._db.execute(
                "INSERT INTO memories (id, topic, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(topic) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at",
                (memory_id, topic, compact, timestamp, timestamp),
            )
            self._db.commit()
            row = self._db.execute("SELECT id, topic, summary, updated_at FROM memories WHERE topic = ?", (topic,)).fetchone()
        return {"id": row["id"], "topic": row["topic"], "summary": row["summary"], "updatedAt": row["updated_at"]}

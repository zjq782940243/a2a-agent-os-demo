"""Host-controlled tools exposed to the Research Agent."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List

from common import new_id


def source_search(topic: str, source_dir: Path, limit: int = 3) -> Dict[str, Any]:
    """Search only the approved local source directory and return evidence."""
    started = time.monotonic()
    terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", topic) if len(term) > 1]
    rows: List[tuple] = []
    for source in sorted(source_dir.glob("*.md")):
        content = source.read_text(encoding="utf-8")
        score = sum(content.lower().count(term) for term in terms)
        rows.append((score, source, content))
    rows.sort(key=lambda row: (-row[0], row[1].name))
    # Never substitute unrelated documents when the query has no evidence.
    # Returning an empty result lets the agent produce an explicit evidence
    # boundary instead of making an unrelated report look authoritative.
    selected = [row for row in rows if row[0] > 0][:limit]
    return {
        "toolCallId": new_id("toolcall"),
        "name": "source_search",
        "input": {"topic": topic, "scope": str(source_dir), "limit": limit},
        "output": {
            "sources": [
                {"path": f"data/sources/{path.name}", "score": score, "content": content.strip()}
                for score, path, content in selected
            ],
            "sourceCount": len(selected),
            "reason": "no_relevant_sources" if not selected else "matched_sources",
        },
        "durationMs": round((time.monotonic() - started) * 1000),
        "status": "completed",
    }

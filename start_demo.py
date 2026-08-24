"""Start all three local services for the A2A demo."""

from __future__ import annotations

import signal
import threading
import time

from orchestrator import Orchestrator
from research_agent import ResearchAgent
from summary_agent import SummaryAgent


def main():
    research = ResearchAgent(8001)
    summary = SummaryAgent(8002)
    orchestrator = Orchestrator(8000)
    servers = [research.serve(), summary.serve(), orchestrator.serve()]
    threads = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    print("A2A Demo is running: http://127.0.0.1:8000")
    print("Agents: research=8001, summary=8002")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.is_set():
            time.sleep(0.5)
    finally:
        for server in servers:
            server.shutdown()


if __name__ == "__main__":
    main()

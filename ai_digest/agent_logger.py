"""
Agent logging: record each agent's inputs, decisions, and outputs to a log file
and echo the same to stdout so you can see how each agent thinks and acts.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import APP_TIMEZONE

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class AgentLogger:
    """
    Logs agent steps to a file in logs/ and to stdout.
    Use one logger per pipeline run (e.g. collect or compose).
    """

    def __init__(
        self,
        phase: str,
        run_id: Optional[str] = None,
        echo: bool = True,
    ):
        self.phase = phase
        self.run_id = run_id or datetime.now(APP_TIMEZONE).strftime("%Y%m%d-%H%M%S")
        self.echo = echo
        self._log_path = LOGS_DIR / f"{phase}_{self.run_id}.log"
        self._file = self._log_path.open("a", encoding="utf-8")

    def _ts(self) -> str:
        return datetime.now(APP_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    def step(
        self,
        agent_name: str,
        action: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one agent step: write to log file and optionally print to stdout."""
        line = f"[{self._ts()}] [{agent_name}] {action}: {message}\n"
        self._file.write(line)
        self._file.flush()
        if self.echo:
            print(line.rstrip())
        if details:
            detail_str = json.dumps(details, ensure_ascii=False, indent=2)
            block = f"  Details:\n" + "\n".join("  " + d for d in detail_str.splitlines()) + "\n"
            self._file.write(block)
            self._file.flush()
            if self.echo:
                print(block.rstrip())

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "AgentLogger":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

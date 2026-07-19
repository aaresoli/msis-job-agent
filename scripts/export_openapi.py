"""Export the FastAPI schema used by the generated frontend client types."""

from __future__ import annotations

import json
from pathlib import Path

from hope_job_agent.main import app


def main() -> int:
    destination = Path(__file__).resolve().parents[1] / "web" / "openapi.json"
    destination.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate committed n8n workflow exports without contacting n8n."""

from __future__ import annotations

import json
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "n8n" / "workflows"
FORBIDDEN = ("api_key", "password", "secret_key")


def validate_workflows() -> list[str]:
    errors: list[str] = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}: invalid JSON: {exc}")
            continue
        if not workflow.get("name") or not workflow.get("nodes"):
            errors.append(f"{path.name}: workflow requires name and nodes")
        serialized = json.dumps(workflow).casefold()
        for forbidden in FORBIDDEN:
            if f'"{forbidden}"' in serialized:
                errors.append(
                    f"{path.name}: contains forbidden secret field {forbidden}"
                )
        for node in workflow.get("nodes", []):
            if "credentials" in node:
                errors.append(
                    f"{path.name}: node {node.get('name')} embeds credentials"
                )
    return errors


def main() -> int:
    errors = validate_workflows()
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Validated {len(list(WORKFLOW_DIR.glob('*.json')))} n8n workflows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

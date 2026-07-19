"""Validate and import the committed workflows into the private n8n container."""

from __future__ import annotations

import argparse
import subprocess

from validate_n8n_workflows import validate_workflows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="Validate without changing n8n"
    )
    args = parser.parse_args()
    errors = validate_workflows()
    if errors:
        raise SystemExit("\n".join(errors))
    if args.check:
        print("n8n workflow imports are valid")
        return 0
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "n8n",
            "n8n",
            "import:workflow",
            "--separate",
            "--input=/workflows",
        ],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

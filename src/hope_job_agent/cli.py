"""Small command-line entry point for starter project checks."""

from hope_job_agent.config import get_settings


def main() -> None:
    """Print a lightweight status message for local smoke testing."""

    settings = get_settings()
    print(f"HOPE Job Agent scaffold running in {settings.environment} mode")


if __name__ == "__main__":
    main()

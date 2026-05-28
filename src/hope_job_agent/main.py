"""FastAPI-ready application entry point."""

from fastapi import FastAPI

app = FastAPI(title="Kelley HOPE MSIS Job Agent")


@app.get("/health")
def health_check() -> dict[str, str]:
    """Basic health endpoint for future container and deployment checks."""

    return {"status": "ok"}

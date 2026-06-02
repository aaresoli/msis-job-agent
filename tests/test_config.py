from pathlib import Path

from hope_job_agent.config import get_settings


def test_environment_config_loads(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = get_settings()

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"


def test_source_config_default_and_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("APPROVED_JOBS_PATH", raising=False)

    default_settings = get_settings()
    assert default_settings.sources.approved_jobs_path == Path(
        "docs/examples/approved_jobs.sample.json"
    )

    export_path = tmp_path / "approved_jobs.json"
    monkeypatch.setenv("APPROVED_JOBS_PATH", str(export_path))

    settings = get_settings()

    assert settings.approved_jobs_path == export_path
    assert settings.sources.approved_jobs_path == export_path


def test_secret_config_masks_plain_text_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example/db")

    settings = get_settings()

    assert settings.openai_api_key.get_secret_value() == "sk-test-secret"
    assert "sk-test-secret" not in repr(settings)
    assert "sk-test-secret" not in repr(settings.secrets)
    assert "password" not in repr(settings)
    assert "password" not in repr(settings.secrets)

from hope_job_agent.config import get_settings


def test_environment_config_loads(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = get_settings()

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"

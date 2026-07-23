"""Coverage for the platform-health gauges and the single-flight lock.

The gauges are what the alerting rules in infra/prometheus/rules/hope.yml fire
on, so a gauge that silently stops being set is an alert that silently stops
working. These tests pin the values the rules depend on.
"""

from __future__ import annotations

import pytest

from hope_job_agent.ops import metrics
from hope_job_agent.ops.locks import AlreadyRunning, single_flight

pytestmark = pytest.mark.unit


def _value(name: str, **labels) -> float | None:
    gauge = getattr(metrics.gauges(), name)
    return gauge.labels(**labels)._value.get() if labels else gauge._value.get()


def test_no_verified_backup_reports_infinite_age_not_missing_data() -> None:
    """A brand-new or totally broken deployment must trip HopeBackupStale.

    Leaving the series absent would make the staleness alert silent in exactly
    the situation it exists for, because `hope_backup_age_seconds > 129600`
    never matches a metric that does not exist.
    """

    class _NoBackups:
        def scalar(self, _statement):  # noqa: ANN001, ANN202
            return None

    from datetime import UTC, datetime

    result = metrics._sample_backup(_NoBackups(), datetime.now(UTC))  # type: ignore[arg-type]

    assert result == {"backup_age_seconds": None, "backup_verified": False}
    assert _value("backup_age") == float("inf")
    assert _value("backup_verified") == 0


def test_an_evicted_model_is_published_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eviction must not look identical to a model that is still resident.

    Without an explicit zero the last "1" would persist forever, and
    HopeModelThrashing would have nothing to correlate against.
    """

    resident: list[str] = ["gpt-oss:120b"]

    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, list[dict[str, str]]]:
            return {"models": [{"model": name} for name in resident]}

    monkeypatch.setattr(
        "hope_job_agent.ops.metrics.get_platform_settings",
        lambda: type("_S", (), {"ollama_base_url": "http://ollama:11434"})(),
    )
    monkeypatch.setattr("httpx.get", lambda *_a, **_k: _Response())

    assert metrics._sample_loaded_models() == ["gpt-oss:120b"]
    assert _value("model_loaded", model="gpt-oss:120b") == 1

    resident.clear()
    assert metrics._sample_loaded_models() == []
    assert _value("model_loaded", model="gpt-oss:120b") == 0


def test_residency_sample_survives_an_unreachable_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unreachable dependency must not take the whole sample down."""

    import httpx

    monkeypatch.setattr(
        "hope_job_agent.ops.metrics.get_platform_settings",
        lambda: type("_S", (), {"ollama_base_url": "http://ollama:11434"})(),
    )

    def _fail(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.get", _fail)

    assert metrics._sample_loaded_models() == []


def test_gauges_are_built_once_per_process() -> None:
    """A worker that never samples must not publish these series at all.

    Module-level Gauges publish at 0 on creation, so every worker that merely
    imported this module exported a fictional hope_backup_last_verified 0 --
    and HopeBackupUnverified (== 0) fired forever.
    """

    assert metrics.gauges() is metrics.gauges()


def test_heartbeat_records_a_timestamp() -> None:
    metrics.record_heartbeat()

    assert _value("beat_heartbeat") > 0


def test_queue_names_match_the_configured_queues() -> None:
    """A queue missing here has no depth gauge and no backlog alert."""

    from hope_job_agent.workers.celery_app import celery_app

    configured = {queue.name for queue in celery_app.conf.task_queues}
    assert set(metrics.QUEUE_NAMES) == configured


def test_single_flight_rejects_a_second_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two overlapping sweeps double the request rate against employer boards."""

    store: dict[str, bytes] = {}

    class _FakeRedis:
        @staticmethod
        def set(key, value, nx=False, ex=None):  # noqa: ANN001, ANN205
            if nx and key in store:
                return None
            store[key] = value
            return True

        @staticmethod
        def eval(_script, _numkeys, key, owner):  # noqa: ANN001, ANN205
            if store.get(key) == owner:
                del store[key]
                return 1
            return 0

    monkeypatch.setattr("hope_job_agent.ops.locks._client", lambda: _FakeRedis())

    with single_flight("refresh-all", 60):
        with pytest.raises(AlreadyRunning):
            with single_flight("refresh-all", 60):
                pass

    # Released on exit, so the next scheduled window can take it.
    assert store == {}
    with single_flight("refresh-all", 60):
        pass


def test_single_flight_release_is_owner_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that overran its TTL must not delete a later run's lock."""

    store: dict[str, bytes] = {}

    class _FakeRedis:
        @staticmethod
        def set(key, value, nx=False, ex=None):  # noqa: ANN001, ANN205
            if nx and key in store:
                return None
            store[key] = value
            return True

        @staticmethod
        def eval(_script, _numkeys, key, owner):  # noqa: ANN001, ANN205
            if store.get(key) == owner:
                del store[key]
                return 1
            return 0

    monkeypatch.setattr("hope_job_agent.ops.locks._client", lambda: _FakeRedis())

    with single_flight("backup", 60):
        # Simulate the TTL expiring and a later run taking the lock.
        store["hope:single-flight:backup"] = b"another-host:999"

    assert store["hope:single-flight:backup"] == b"another-host:999"

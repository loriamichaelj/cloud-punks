"""Hermetic tests of cloud_drills: no cluster, no Prometheus, no AWS."""

from typing import Any

import cloud_drills
import pytest
from cloud_drills import alert_state, env_override, prom_value


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    def json(self) -> dict[str, Any]:
        return self.body


def answer(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> None:
    monkeypatch.setattr(cloud_drills.httpx2, "get", lambda *a, **k: FakeResponse(body))


def series(*values: str) -> dict[str, Any]:
    return {"data": {"result": [{"metric": {}, "value": [0, v]} for v in values]}}


def test_prom_value_sums_the_series(monkeypatch: pytest.MonkeyPatch) -> None:
    answer(monkeypatch, series("2", "3.5"))
    assert prom_value("x") == 5.5


def test_prom_value_is_none_when_nothing_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    answer(monkeypatch, series())
    assert prom_value("x") is None


def alerts(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"data": {"alerts": [{"labels": {"alertname": n}, "state": s} for n, s in pairs]}}


def test_alert_state_prefers_firing_then_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    answer(
        monkeypatch, alerts(("OutboxLag", "pending"), ("OutboxLag", "firing"), ("Other", "firing"))
    )
    assert alert_state("OutboxLag") == "firing"
    answer(monkeypatch, alerts(("OutboxLag", "pending")))
    assert alert_state("OutboxLag") == "pending"


def test_alert_state_is_inactive_when_it_is_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    answer(monkeypatch, alerts(("Other", "firing")))
    assert alert_state("OutboxLag") == "inactive"


def record_kubectl(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(cloud_drills, "kubectl", lambda *args, **kw: calls.append(args) or "")
    return calls


def test_env_override_sets_waits_then_removes_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_kubectl(monkeypatch)
    with env_override("order-relay", EVENT_BUS_NAME="nope"):
        assert calls == [
            ("set", "env", "deploy/order-relay", "EVENT_BUS_NAME=nope"),
            ("rollout", "status", "deploy/order-relay", "--timeout=180s"),
        ]
    assert calls[2:] == [
        ("set", "env", "deploy/order-relay", "EVENT_BUS_NAME-"),
        ("rollout", "status", "deploy/order-relay", "--timeout=180s"),
    ]


def test_env_override_puts_the_value_back_when_the_block_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = record_kubectl(monkeypatch)
    with (
        pytest.raises(RuntimeError, match="boom"),
        env_override("order-relay", EVENT_BUS_NAME="nope"),
    ):
        raise RuntimeError("boom")
    assert ("set", "env", "deploy/order-relay", "EVENT_BUS_NAME-") in calls

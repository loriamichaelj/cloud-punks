"""What the cloud drills (test_cloud_drills.py) share: asking Prometheus, and overriding a Deployment's env.

The drills break one thing on the dev EKS cluster by changing configuration, never an AWS resource, and put
it back. Prometheus is how they see the platform notice (the deploy role cannot read CloudWatch alarms or
the queues); the alarms and alerts also send email, which is what a person checks by eye.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx2
from k8s_compose import kubectl  # scripts/: every call names --context and the namespace

PROMETHEUS_URL = os.environ.get("E2E_PROMETHEUS_URL", "http://localhost:9090")
ROLLOUT_TIMEOUT = "--timeout=180s"


def prom_value(expression: str) -> float | None:
    """The sum of the series ``expression`` returns, or None when it returns none."""
    response = httpx2.get(
        f"{PROMETHEUS_URL}/api/v1/query", params={"query": expression}, timeout=10
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]["result"]
    if not result:
        return None
    return sum(float(series["value"][1]) for series in result)


def alert_state(name: str) -> str:
    """``firing``, ``pending`` or ``inactive`` for the Prometheus alert called ``name``."""
    response = httpx2.get(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=10)
    assert response.status_code == 200, response.text
    states = {
        alert["state"]
        for alert in response.json()["data"]["alerts"]
        if alert["labels"].get("alertname") == name
    }
    if "firing" in states:
        return "firing"
    return "pending" if "pending" in states else "inactive"


@contextmanager
def env_override(deployment: str, **env: str) -> Iterator[None]:
    """Set container env vars on a Deployment and wait for the rollout; remove them again however it ends.

    An env var on the container wins over the same name from the chart's ConfigMap, and removing it
    brings the ConfigMap's value back, so what the chart configured is never edited.
    """
    target = f"deploy/{deployment}"
    kubectl("set", "env", target, *(f"{name}={value}" for name, value in env.items()))
    try:
        kubectl("rollout", "status", target, ROLLOUT_TIMEOUT)
        yield
    finally:
        kubectl("set", "env", target, *(f"{name}-" for name in env))
        kubectl("rollout", "status", target, ROLLOUT_TIMEOUT)

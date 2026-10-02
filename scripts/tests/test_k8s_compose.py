"""scripts/k8s_compose.py: which cluster it talks to, and what it does with no Compose at all."""

import json
import subprocess
from typing import Any

import k8s_compose
import pytest


class Recorder:
    """Stands in for subprocess.run: records each command, answers every one with an empty list."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='{"items": []}', stderr="")


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    for name in ("K8S_CONTEXT", "K8S_NAMESPACE", "K8S_COMPOSE_REAL"):
        monkeypatch.delenv(name, raising=False)
    recorder = Recorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    return recorder


def test_by_default_it_names_the_local_cluster_and_the_retail_namespace(run: Recorder) -> None:
    k8s_compose.kubectl("get", "pods")

    assert run.commands == [["kubectl", "--context", "orbstack", "-n", "retail", "get", "pods"]]


def test_the_context_and_namespace_can_be_set_for_another_cluster(
    run: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("K8S_CONTEXT", "loria-retail-dev")
    monkeypatch.setenv("K8S_NAMESPACE", "retail-test")

    k8s_compose.kubectl("get", "deploy")

    assert run.commands == [
        ["kubectl", "--context", "loria-retail-dev", "-n", "retail-test", "get", "deploy"]
    ]


def test_an_empty_context_falls_back_to_the_local_one_and_never_to_the_current_context(
    run: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("K8S_CONTEXT", "")

    k8s_compose.kubectl("get", "pods")

    assert run.commands[0][:3] == ["kubectl", "--context", "orbstack"]


def test_every_kubectl_command_the_shim_builds_carries_a_context(
    run: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("K8S_CONTEXT", "loria-retail-dev")
    deploy = {"metadata": {"annotations": {}}, "spec": {"replicas": 0}, "status": {}}

    k8s_compose.stop("inventory-consumer")
    k8s_compose.start("inventory-consumer", deploy)
    k8s_compose.restarts("inventory-consumer")

    assert run.commands
    assert all(c[:3] == ["kubectl", "--context", "loria-retail-dev"] for c in run.commands)


def test_without_compose_ps_lists_only_the_deployments(
    run: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2}}

    k8s_compose.ps_json({"order-service": deploy})

    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows == [{"Service": "order-service", "State": "running", "Health": "healthy"}]
    assert run.commands == []  # no `docker compose ps`: there is no Compose in the cloud


def test_a_deployment_that_is_not_fully_ready_is_reported_unhealthy(
    run: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = {"spec": {"replicas": 2}, "status": {"readyReplicas": 1}}

    k8s_compose.ps_json({"order-service": deploy})

    assert json.loads(capsys.readouterr().out)["Health"] == "unhealthy"

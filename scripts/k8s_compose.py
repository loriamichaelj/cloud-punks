"""Answer the few ``docker compose`` commands the e2e suites use, for the local Kubernetes cluster.

``tests/e2e`` and ``ui/e2e`` stop and start processes, read logs, run commands inside a process
and ask whether everything is healthy, all through one command given in ``E2E_COMPOSE``. For
``make k8s-e2e`` that command is this script, so the same tests run unchanged against the cluster:

* a name that is a Deployment in namespace ``retail`` (an API, consumer, relay or the UI) is
  handled with kubectl: ``stop`` scales it to 0, ``start`` scales it back to the count the chart
  recorded and waits for the rollout;
* anything else (postgres, valkey, localstack, which stay in Compose on the Mac) is passed to the
  real ``docker compose``, whose command is in ``K8S_COMPOSE_REAL``.

Every kubectl call names ``--context orbstack``. Also: ``kill-pod`` and ``scrape`` (used by the
Kubernetes-only tests), ``restarts``. Not supported (that drill runs on Compose): ``run``.
"""

import json
import os
import shlex
import subprocess
import sys

CONTEXT = "orbstack"
NAMESPACE = "retail"
KUBECTL = ["kubectl", "--context", CONTEXT, "-n", NAMESPACE]
INFRA = {"postgres", "valkey", "localstack"}
DESIRED = "retail.io/desired-replicas"


def kubectl(*args: str, check: bool = True) -> str:
    command = [*KUBECTL, *args]
    done = subprocess.run(command, capture_output=True, text=True, check=check, timeout=300)  # noqa: S603
    return done.stdout


def selector(name: str) -> list[str]:
    return ["-l", f"app.kubernetes.io/name={name}"]


def pods_of(name: str) -> list[dict]:
    return json.loads(kubectl("get", "pods", *selector(name), "-o", "json"))["items"]


def real_compose(*args: str) -> int:
    command = os.environ.get("K8S_COMPOSE_REAL")
    if not command:
        sys.stderr.write("K8S_COMPOSE_REAL is not set: run through `make k8s-e2e`\n")
        return 2
    return subprocess.run([*shlex.split(command), *args], check=False).returncode  # noqa: S603


def deployments() -> dict[str, dict]:
    items = json.loads(kubectl("get", "deploy", "-o", "json"))["items"]
    return {item["metadata"]["name"]: item for item in items}


def scale(name: str, replicas: int) -> None:
    kubectl("scale", f"deploy/{name}", f"--replicas={replicas}")


def stop(name: str) -> None:
    scale(name, 0)
    kubectl("wait", "--for=delete", "pod", *selector(name), "--timeout=90s", check=False)


def start(name: str, deploy: dict) -> None:
    scale(name, int(deploy["metadata"]["annotations"].get(DESIRED, "1")))
    kubectl("rollout", "status", f"deploy/{name}", "--timeout=180s")


def ps_json(known: dict[str, dict]) -> None:
    for name, deploy in sorted(known.items()):
        wanted = deploy["spec"].get("replicas", 0)
        ready = deploy["status"].get("readyReplicas", 0)
        healthy = wanted > 0 and ready >= wanted
        row = {
            "Service": name,
            "State": "running" if ready else "exited",
            "Health": "healthy" if healthy else "unhealthy",
        }
        print(json.dumps(row))
    command = [*shlex.split(os.environ["K8S_COMPOSE_REAL"]), "ps", "--format", "json"]
    done = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    for line in done.stdout.splitlines():
        if line.strip() and json.loads(line).get("Service") in INFRA:
            print(line)


def logs(known: dict[str, dict], since: str) -> None:
    for name in sorted(known):
        flags = [f"--since={since}", "--max-log-requests=10", "--tail=-1"]
        out = kubectl("logs", *selector(name), *flags, check=False)
        for line in out.splitlines():
            print(f"{name}-1  | {line}")


def restarts(name: str) -> None:
    statuses = [c for p in pods_of(name) for c in p["status"].get("containerStatuses", [])]
    print(sum(c["restartCount"] for c in statuses))


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    command, rest = argv[0], argv[1:]
    known = deployments()
    targets = [a for a in rest if a in known]
    if command in ("stop", "start") and rest and all(a in known for a in rest):
        for name in rest:
            if command == "stop":
                stop(name)
            else:
                start(name, known[name])
        return 0
    if command in ("stop", "start"):
        return real_compose(*argv)
    if command == "ps" and "--format" in rest:
        ps_json(known)
        return 0
    if command == "logs":
        since = rest[rest.index("--since") + 1] if "--since" in rest else "2m"
        logs(known, since)
        return 0
    if command == "scrape":  # scrape <service> <port>: every pod's /metrics, concatenated
        service, port = rest
        url = f"http://127.0.0.1:{int(port)}/metrics"
        fetch = f"import urllib.request as u;print(u.urlopen('{url}').read().decode())"
        for pod in pods_of(service):
            pod_name = pod["metadata"]["name"]
            print(f"# pod={pod_name}")  # lets a caller compare only pods present in both scrapes
            sys.stdout.write(kubectl("exec", pod_name, "-c", "app", "--", "python", "-c", fetch))
        return 0
    if command == "kill-pod":  # kill-pod <service>: delete one pod, gracefully (kubectl delete pod)
        names = [p["metadata"]["name"] for p in pods_of(rest[0])]
        kubectl("delete", "pod", names[0], "--wait=false")
        print(names[0])
        return 0
    if command == "restarts":
        restarts(rest[0])
        return 0
    if command == "exec" and targets:
        service = targets[0]
        tail = rest[rest.index(service) + 1 :]
        sys.stdout.write(kubectl("exec", f"deploy/{service}", "-c", "app", "--", *tail))
        return 0
    if command == "run":
        sys.stderr.write("`run` is not supported on Kubernetes: that drill runs on Compose\n")
        return 2
    return real_compose(*argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

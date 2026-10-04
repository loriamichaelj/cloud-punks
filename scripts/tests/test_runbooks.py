"""The runbooks and the alarms must stay in step: an alert that names a missing runbook, or an alarm that no
runbook mentions, is found here and not during an incident."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = ROOT / "docs" / "runbooks"
RULES = ROOT / "deploy" / "helm" / "monitoring" / "rules" / "retail.yml"
MONITORING = ROOT / "infra" / "terraform" / "modules" / "monitoring" / "main.tf"
EVENTS = ROOT / "infra" / "terraform" / "modules" / "events" / "main.tf"
ALB = ROOT / "infra" / "terraform" / "envs" / "dev" / "alb-alarms" / "main.tf"


def index() -> str:
    return (RUNBOOKS / "README.md").read_text()


def runbook_files() -> list[Path]:
    return sorted(p for p in RUNBOOKS.glob("*.md") if p.name != "README.md")


def test_every_runbook_an_alert_names_exists() -> None:
    paths = re.findall(r"runbook: (\S+)", RULES.read_text())
    assert paths, "the rules name no runbooks"
    assert [p for p in paths if not (ROOT / p).is_file()] == []


def test_every_prometheus_alert_is_in_the_index() -> None:
    alerts = re.findall(r"- alert: (\w+)", RULES.read_text())
    assert alerts
    assert [a for a in alerts if f"`{a}`" not in index()] == []


def test_every_cloudwatch_alarm_is_in_the_index() -> None:
    fixed = re.findall(r'^\s+"((?:db|lambda)-[a-z-]+)" = \{', MONITORING.read_text(), re.M)
    fixed += re.findall(r'alarm_name\s*=\s*"\$\{var\.name\}-(alb-[a-z0-9-]+)"', ALB.read_text())
    routes = re.findall(r'^\s+"(to-[a-z]+)" = \{', EVENTS.read_text(), re.M)
    per_route = [
        f"{family}-{route}" for family in ("queue-age", "dlq", "rule-failed") for route in routes
    ]
    per_route += ["dlq-low-stock", "rule-failed-low-stock"]
    # the patterns above still match something, or this test would pass on nothing
    assert len(fixed) >= 7, fixed
    assert len(routes) == 3, routes
    missing = [name for name in [*fixed, *per_route] if f"`{name}`" not in index()]
    assert missing == []


def test_every_runbook_is_linked_from_the_index() -> None:
    files = runbook_files()
    assert len(files) >= 5
    assert [f.name for f in files if f"({f.name})" not in index()] == []


def test_every_link_between_runbooks_resolves() -> None:
    broken = []
    for doc in [RUNBOOKS / "README.md", *runbook_files()]:
        for target in re.findall(r"\]\(([^)#]+\.md)\)", doc.read_text()):
            if not (doc.parent / target).is_file():
                broken.append((doc.name, target))
    assert broken == []

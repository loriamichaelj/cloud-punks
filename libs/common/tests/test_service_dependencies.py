"""Every service must declare what it imports.

The workspace shares one virtual environment, so a service can import a package that only some
*other* service declares and every test still passes. The service's Docker image installs only its
own declared dependencies, so it then crashes at startup (this happened: order-service used
Alembic without declaring it). This test reads each service's imports and requires every
third-party one to be a declared dependency or a transitive dependency of one.
"""

import ast
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[3]
SERVICES = sorted(path.parent for path in (ROOT / "services").glob("*/pyproject.toml"))
FIRST_PARTY = {"app", "retail_common", "seed", "catalog"}  # a service's own code and its seed job
EXTRA_SOURCES = {"product-service": [ROOT / "local" / "seed"]}  # shipped in the image


def declared(service: Path) -> set[str]:
    project = tomllib.loads((service / "pyproject.toml").read_text())["project"]
    return {canonicalize_name(Requirement(spec).name) for spec in project["dependencies"]}


def closure(roots: set[str]) -> set[str]:
    """The declared distributions plus everything they depend on, transitively."""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        for spec in requires:
            requirement = Requirement(spec)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                todo.append(canonicalize_name(requirement.name))
    return seen


def imported_modules(directories: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for directory in directories:
        for path in directory.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for name in names:
                    top = name.split(".")[0]
                    if top not in sys.stdlib_module_names and top not in FIRST_PARTY:
                        found.setdefault(top, path)
    return found


@pytest.mark.parametrize("service", SERVICES, ids=lambda path: path.name)
def test_every_import_resolves_to_a_declared_dependency(service: Path) -> None:
    owners = metadata.packages_distributions()
    allowed = closure(declared(service))
    directories = [service / "app", *EXTRA_SOURCES.get(service.name, [])]

    undeclared = {}
    for module, path in imported_modules(directories).items():
        distributions = {canonicalize_name(d) for d in owners.get(module, [])}
        if not distributions & allowed:
            undeclared[module] = str(path.relative_to(ROOT))

    assert undeclared == {}, (
        f"{service.name} imports packages its pyproject.toml does not declare (its image would "
        f"crash at start): {undeclared}"
    )


def test_the_check_sees_the_services() -> None:
    assert {s.name for s in SERVICES} == {
        "inventory-service", "notification-service", "order-service", "product-service",
    }  # fmt: skip

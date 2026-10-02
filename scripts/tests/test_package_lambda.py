"""scripts/package_lambda.py: the Lambda zip must be correct, and identical every time it is built."""

import importlib.util
import os
import stat
import zipfile
import zipimport
from pathlib import Path

import package_lambda
import pytest


def build(tmp_path: Path, name: str = "out.zip", source: Path = package_lambda.SOURCE) -> Path:
    return package_lambda.build(source=source, output=tmp_path / name)


def test_the_zip_holds_exactly_handler_py_at_its_root(tmp_path: Path) -> None:
    with zipfile.ZipFile(build(tmp_path)) as archive:
        assert archive.namelist() == ["handler.py"]
        assert archive.read("handler.py") == package_lambda.SOURCE.read_bytes()


def test_building_twice_gives_identical_bytes(tmp_path: Path) -> None:
    first = build(tmp_path, "a.zip").read_bytes()
    second = build(tmp_path, "b.zip").read_bytes()

    assert first == second


def test_the_bytes_do_not_depend_on_the_source_files_modification_time(tmp_path: Path) -> None:
    """Plan and apply check out the repository on different machines, so the mtime differs."""
    source = tmp_path / "handler.py"
    source.write_bytes(package_lambda.SOURCE.read_bytes())
    before = build(tmp_path, "a.zip", source).read_bytes()

    os.utime(source, (1_000_000_000, 1_000_000_000))
    after = build(tmp_path, "b.zip", source).read_bytes()

    assert before == after


def test_the_entry_has_the_fixed_timestamp_a_plain_mode_and_no_compression(tmp_path: Path) -> None:
    with zipfile.ZipFile(build(tmp_path)) as archive:
        info = archive.getinfo("handler.py")

    assert info.date_time == package_lambda.FIXED_TIME
    assert info.compress_type == zipfile.ZIP_STORED
    mode = info.external_attr >> 16
    assert stat.S_ISREG(mode)
    assert stat.S_IMODE(mode) == 0o644


def test_the_handler_runs_when_imported_from_the_zip(tmp_path: Path) -> None:
    """What Lambda does: put the zip on the path and import ``handler``."""
    archive = build(tmp_path)
    spec = zipimport.zipimporter(str(archive)).find_spec("handler")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    event = {"detail": {"data": {"order_id": "01TEST", "items": [{"sku": "A", "remaining": 2}]}}}

    assert module.lambda_handler(event, None) == {"low_stock": 1}


def test_a_missing_source_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        package_lambda.build(source=tmp_path / "nope.py", output=tmp_path / "out.zip")
    assert not (tmp_path / "out.zip").exists()


def test_main_builds_the_zip_prints_its_path_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "nested" / "out.zip"

    assert package_lambda.main([str(target)]) == 0
    assert capsys.readouterr().out.strip() == str(target)
    assert zipfile.is_zipfile(target)


def test_main_returns_one_and_says_why_when_the_build_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(output: Path) -> Path:
        raise FileNotFoundError("the Lambda source is missing: handler.py")

    monkeypatch.setattr(package_lambda, "build", fail)

    assert package_lambda.main([str(tmp_path / "out.zip")]) == 1
    assert "missing" in capsys.readouterr().err

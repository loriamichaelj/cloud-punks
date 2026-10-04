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


def test_main_builds_both_zips_in_the_directory_prints_their_paths_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "nested"

    assert package_lambda.main([str(target)]) == 0
    printed = capsys.readouterr().out.split()
    assert printed == [
        str(target / "low-stock-alert.zip"),
        str(target / "market-activity-email.zip"),
    ]
    assert all(zipfile.is_zipfile(path) for path in printed)


def test_main_returns_one_and_says_why_when_the_build_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(output: Path) -> Path:
        raise FileNotFoundError("the Lambda source is missing: handler.py")

    monkeypatch.setattr(package_lambda, "build", fail)

    assert package_lambda.main([str(tmp_path)]) == 1
    assert "missing" in capsys.readouterr().err


# -- market-activity-email ------------------------------------------------------------------------


def test_the_email_zip_holds_the_handler_and_the_hundred_svgs_in_order(tmp_path: Path) -> None:
    with zipfile.ZipFile(package_lambda.build_email(tmp_path / "email.zip")) as archive:
        names = archive.namelist()
        assert names[0] == "handler.py"
        assert names[1:] == [f"art/{n:04d}.svg" for n in range(1, 101)]
        assert archive.read("art/0023.svg") == (package_lambda.ART / "0023.svg").read_bytes()
        assert all(archive.getinfo(n).date_time == package_lambda.FIXED_TIME for n in names)


def test_the_email_zip_is_identical_every_time(tmp_path: Path) -> None:
    first = package_lambda.build_email(tmp_path / "a.zip").read_bytes()
    second = package_lambda.build_email(tmp_path / "b.zip").read_bytes()
    assert first == second


def test_the_email_handler_finds_its_art_inside_the_zip(tmp_path: Path) -> None:
    """As Lambda unpacks it: the handler next to art/, drawing a CloudPunk from there."""
    archive = package_lambda.build_email(tmp_path / "email.zip")
    unpacked = tmp_path / "task"
    with zipfile.ZipFile(archive) as z:
        z.extractall(unpacked)
    spec = importlib.util.spec_from_file_location("email_handler", unpacked / "handler.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    svg = module.art_for("CP-0023")
    assert svg is not None
    assert module.png(module.pixels(svg, module.OWNED)).startswith(b"\x89PNG")


def test_an_incomplete_collection_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "art").mkdir()
    (tmp_path / "art" / "0001.svg").write_text("<svg/>")
    with pytest.raises(FileNotFoundError, match="found 1"):
        package_lambda.build_email(tmp_path / "email.zip", art=tmp_path / "art")

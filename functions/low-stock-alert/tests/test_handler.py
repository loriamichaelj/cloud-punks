import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import handler


def event(*items: tuple[str, int]) -> dict[str, Any]:
    return {
        "detail-type": "InventoryReserved",
        "detail": {
            "event_id": "01J9Z6R0C4AAAAAAAAAAAAAAAA",
            "correlation_id": "corr-1",
            "data": {
                "order_id": "01J9Z6R0C4BBBBBBBBBBBBBBBB",
                "items": [{"sku": s, "quantity": 1, "remaining": r} for s, r in items],
            },
        },
    }


def records(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


@pytest.fixture(autouse=True)
def _default_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOW_STOCK_THRESHOLD", raising=False)


def test_an_item_below_the_threshold_is_logged_with_the_metric(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = handler.lambda_handler(event(("A", 4)), None)

    (record,) = records(capsys)
    assert result == {"low_stock": 1}
    assert (record["event"], record["sku"], record["remaining"]) == ("low_stock", "A", 4)
    assert record["order_id"] == "01J9Z6R0C4BBBBBBBBBBBBBBBB"
    assert record["correlation_id"] == "corr-1"
    metric = record["_aws"]["CloudWatchMetrics"][0]
    assert metric["Metrics"][0]["Name"] == "LowStockDetected"
    assert record["LowStockDetected"] == 1
    assert all(d in record for d in metric["Dimensions"][0])  # every dimension has a value


def test_the_threshold_is_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    result = handler.lambda_handler(event(("AT", 5), ("OVER", 50), ("ZERO", 0)), None)

    assert result == {"low_stock": 1}
    assert [r["sku"] for r in records(capsys)] == ["ZERO"]


def test_the_threshold_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOW_STOCK_THRESHOLD", "20")

    assert handler.lambda_handler(event(("A", 19), ("B", 20)), None) == {"low_stock": 1}
    assert records(capsys)[0]["threshold"] == 20


def test_a_bad_threshold_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOW_STOCK_THRESHOLD", "lots")
    assert handler.lambda_handler(event(("A", 4)), None) == {"low_stock": 1}


def test_each_low_item_gets_its_own_record(capsys: pytest.CaptureFixture[str]) -> None:
    handler.lambda_handler(event(("A", 1), ("B", 2)), None)
    assert [r["sku"] for r in records(capsys)] == ["A", "B"]


@pytest.mark.parametrize(
    "bad",
    [{}, {"detail": None}, {"detail": {"data": {}}}, {"detail": {"data": {"items": "x"}}}],
)
def test_a_malformed_event_is_logged_not_raised(
    bad: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert handler.lambda_handler(bad, None) == {"low_stock": 0}
    assert records(capsys)[0]["event"] == "malformed_event"


def test_items_that_are_not_stock_lines_are_skipped(capsys: pytest.CaptureFixture[str]) -> None:
    odd = event(("A", 1))
    odd["detail"]["data"]["items"] += [None, {"sku": "B"}, {"sku": "C", "remaining": True}]

    assert handler.lambda_handler(odd, None) == {"low_stock": 1}

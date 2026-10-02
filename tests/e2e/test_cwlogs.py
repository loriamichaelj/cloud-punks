"""Hermetic tests of ``cwlogs.find_log_message``: a fake client, no AWS, no stack."""

from typing import Any

import pytest
from cwlogs import MAX_PAGES, find_log_message, releases_that_logged


class FakeLogs:
    """Returns the given pages in order and records every call's arguments."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def filter_log_events(self, **params: Any) -> dict[str, Any]:
        self.calls.append(dict(params))
        return self.pages[min(len(self.calls), len(self.pages)) - 1]


def event(message: str) -> dict[str, str]:
    return {"message": message}


def test_a_record_on_a_later_page_is_found_after_an_empty_first_page() -> None:
    logs = FakeLogs(
        [{"events": [], "nextToken": "t1"}, {"events": [event("order 01ABC low_stock")]}]
    )
    assert find_log_message(logs, "g", "01ABC", since_ms=5) == "order 01ABC low_stock"
    assert [c.get("nextToken") for c in logs.calls] == [None, "t1"]


def test_the_query_is_bounded_in_time_and_filtered_on_the_quoted_term() -> None:
    logs = FakeLogs([{"events": [event("01ABC")]}])
    find_log_message(logs, "/aws/lambda/x", "01ABC", since_ms=1234)
    assert logs.calls[0] == {
        "logGroupName": "/aws/lambda/x",
        "startTime": 1234,
        "filterPattern": '"01ABC"',
    }


def test_an_event_that_does_not_contain_the_term_is_not_a_match() -> None:
    logs = FakeLogs([{"events": [event("some other order")]}])
    assert find_log_message(logs, "g", "01ABC", since_ms=0) is None


def test_none_when_the_last_page_has_no_match_and_no_token() -> None:
    logs = FakeLogs([{"events": [], "nextToken": "t1"}, {"events": []}])
    assert find_log_message(logs, "g", "01ABC", since_ms=0) is None
    assert len(logs.calls) == 2


def test_a_service_that_never_stops_returning_a_token_is_given_up_on() -> None:
    logs = FakeLogs([{"events": [], "nextToken": "again"}])
    assert find_log_message(logs, "g", "01ABC", since_ms=0) is None
    assert len(logs.calls) == MAX_PAGES


class FakeInsights:
    """start_query returns an id; get_query_results answers with the given statuses in order."""

    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers = answers
        self.started: list[dict[str, Any]] = []
        self.stopped = False

    def start_query(self, **params: Any) -> dict[str, str]:
        self.started.append(params)
        return {"queryId": "q1"}

    def get_query_results(self, queryId: str) -> dict[str, Any]:
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    def stop_query(self, queryId: str) -> None:
        self.stopped = True


def row(pod: str, lines: str) -> list[dict[str, str]]:
    return [{"field": "kubernetes.pod_name", "value": pod}, {"field": "lines", "value": lines}]


def test_pods_are_folded_into_their_releases_and_lines_are_summed() -> None:
    logs = FakeInsights(
        [
            {"status": "Running", "results": []},
            {
                "status": "Complete",
                "results": [
                    row("order-service-78d4568df6-dsh4m", "3"),
                    row("order-service-78d4568df6-sfjtx", "1"),
                    row("inventory-consumer-7b49f77c58-65vz6", "2"),
                ],
            },
        ]
    )
    seen = releases_that_logged(logs, "g", "e2e-corr-abc", start_s=10, end_s=20)
    assert seen == {"order-service": 4, "inventory-consumer": 2}
    assert logs.started[0]["startTime"] == 10
    assert 'like "e2e-corr-abc"' in logs.started[0]["queryString"]


def test_nothing_matched_is_an_empty_result() -> None:
    logs = FakeInsights([{"status": "Complete", "results": []}])
    assert releases_that_logged(logs, "g", "e2e-corr-abc", start_s=0, end_s=1) == {}


def test_a_failed_query_is_an_error_not_an_empty_result() -> None:
    logs = FakeInsights([{"status": "Failed", "results": []}])
    with pytest.raises(AssertionError, match="Failed"):
        releases_that_logged(logs, "g", "e2e-corr-abc", start_s=0, end_s=1)


def test_a_query_that_never_finishes_is_stopped() -> None:
    logs = FakeInsights([{"status": "Running", "results": []}])
    with pytest.raises(AssertionError, match="did not finish"):
        releases_that_logged(logs, "g", "e2e-corr-abc", start_s=0, end_s=1, timeout_s=0)
    assert logs.stopped


def test_an_id_that_could_change_the_query_is_refused() -> None:
    logs = FakeInsights([{"status": "Complete", "results": []}])
    with pytest.raises(ValueError, match="not a plain id"):
        releases_that_logged(logs, "g", 'x" | stats count(*) by @log', start_s=0, end_s=1)
    assert logs.started == []

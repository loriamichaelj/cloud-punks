"""Finding one record in a CloudWatch Logs group.

Real CloudWatch differs from LocalStack in ways a single ``filter_log_events`` call hides: a page
can come back with no events and a ``nextToken`` while the service is still scanning, and a group
keeps every earlier run's records. So the query is bounded in time, filtered on the term, and
follows ``nextToken`` to the end.
"""

from typing import Any

MAX_PAGES = 50  # a bound, so a service that always returns a token cannot hang the test


def find_log_message(logs: Any, group: str, needle: str, *, since_ms: int) -> str | None:
    """The first message in ``group`` since ``since_ms`` (epoch milliseconds) that contains ``needle``."""
    params: dict[str, Any] = {
        "logGroupName": group,
        "startTime": since_ms,
        "filterPattern": f'"{needle}"',  # a quoted term: match it exactly, not as filter syntax
    }
    for _ in range(MAX_PAGES):
        page = logs.filter_log_events(**params)
        for event in page.get("events", []):
            if needle in event["message"]:  # the pattern is a hint; the match is made here
                return str(event["message"])
        token = page.get("nextToken")
        if not token:
            return None
        params["nextToken"] = token
    return None

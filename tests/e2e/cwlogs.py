"""Reading a CloudWatch Logs group the way the real service needs: one record, or one id across processes.

Real CloudWatch differs from LocalStack in ways a single ``filter_log_events`` call hides: a page
can come back with no events and a ``nextToken`` while the service is still scanning, and a group
keeps every earlier run's records. So the query is bounded in time, filtered on the term, and
follows ``nextToken`` to the end.
"""

import re
import time
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


def releases_that_logged(
    logs: Any, group: str, needle: str, *, start_s: int, end_s: int, timeout_s: float = 60
) -> dict[str, int]:
    """Logs Insights: how many lines containing ``needle`` each Helm release logged in the window.

    Every container in the chart is named ``app``, so the release comes from the pod name
    (``order-consumer-56948d798c-gpv9n`` is ``order-consumer``). Returns {} when nothing matched.
    Raises AssertionError if the query fails or does not finish within ``timeout_s``.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", needle):  # it goes into the query text
        raise ValueError(f"not a plain id: {needle!r}")
    query = f'filter @message like "{needle}" | stats count(*) as lines by kubernetes.pod_name'
    query_id = logs.start_query(
        logGroupName=group, startTime=start_s, endTime=end_s, queryString=query
    )["queryId"]
    deadline = time.monotonic() + timeout_s
    while True:
        result = logs.get_query_results(queryId=query_id)
        if result["status"] == "Complete":
            break
        if result["status"] in ("Failed", "Cancelled", "Timeout"):
            raise AssertionError(f"the Logs Insights query ended as {result['status']}")
        if time.monotonic() > deadline:
            logs.stop_query(queryId=query_id)
            raise AssertionError(f"the Logs Insights query did not finish in {timeout_s}s")
        time.sleep(1)

    seen: dict[str, int] = {}
    for row in result["results"]:
        columns = {c["field"]: c["value"] for c in row}
        pod = columns.get("kubernetes.pod_name", "")
        release = pod.rsplit("-", 2)[0] if pod.count("-") >= 2 else pod
        seen[release] = seen.get(release, 0) + int(columns.get("lines", "0"))
    return seen

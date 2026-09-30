"""low-stock-alert Lambda: M2 stub so the LocalStack bootstrap can create the function.

M7 replaces this with the real handler (structured low_stock log + EMF metric).
"""

from typing import Any


def lambda_handler(event: dict[str, Any], context: object) -> None:
    return None

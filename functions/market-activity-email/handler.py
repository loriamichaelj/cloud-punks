"""market-activity-email Lambda (DESIGN.md section 16.11).

EventBridge invokes it for every ``MarketActivity`` event on a CloudPunk (the rule matches
``detail.data.sku`` prefix ``CP-``): up for bid, taken off, a bid placed or withdrawn, a sale. It
sends one email through SES: the CloudPunk's picture on the colour of its state after the activity,
what happened, the price and who. The picture is drawn here from the CloudPunk's SVG (packaged
under ``art/``) as a PNG, because mail clients show an inline PNG and not an SVG. Standard library
plus the boto3 that the Lambda runtime provides.

At least once: an SES error is raised, so the asynchronous invoke retries and then dead-letters;
a retry after a send that did reach SES can deliver the same email twice, which is harmless and
is why this function keeps no store (DESIGN.md section 16.11). A malformed event, a kind this build
does not know or a SKU without art is logged and dropped: it can never succeed.

Configuration from the environment only: EMAIL_FROM and EMAIL_TO (a verified SES identity), and
optionally STOREFRONT_URL for a link. The address is never logged.
"""

import html
import json
import os
import re
import struct
import time
import zlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import make_msgid
from pathlib import Path
from typing import Any

SERVICE = "market-activity-email"
ART = Path(__file__).resolve().parent / "art"
GRID = 24  # every CloudPunk is 24 x 24 pixels
SCALE = 10  # drawn at 240 x 240
SKU = re.compile(r"^CP-(\d{4})$")
RECT = re.compile(r"<rect\s([^>]*?)/?>")
ATTRIBUTE = re.compile(r'([a-z-]+)="([^"]*)"')

# The tile colours of the UI (ui/src/styles/global.css): purple up for bid, blue-grey owned.
BID = (0x85, 0x71, 0xAD)
OWNED = (0x6F, 0x83, 0x92)

# kind -> (state after it, its colour, the subject with {name} and {price}, the headline verb)
KINDS: dict[str, tuple[str, tuple[int, int, int], str, str]] = {
    "LISTED": ("Up for bid", BID, "{name} is up for bid", "was put up for bid"),
    "UNLISTED": ("Owned", OWNED, "{name} was taken off the market", "was taken off the market"),
    "BID_PLACED": ("Up for bid", BID, "New bid on {name}: {price}", "has a new bid"),
    "BID_WITHDRAWN": ("Up for bid", BID, "Bid withdrawn on {name}", "had a bid withdrawn"),
    "SALE": ("Owned", OWNED, "{name} sold for {price}", "was sold"),
}

# Mail clients ignore stylesheets, so the HTML part is styled inline (the UI's dark theme).
PAGE = "margin:0;padding:24px;background:#121212;font-family:-apple-system,Segoe UI,sans-serif"
CARD = (
    "width:100%;max-width:480px;margin:0 auto;padding:24px;background:#1b1b1d;"
    "border:1px solid #303036;border-radius:16px"
)
PICTURE = "display:block;border-radius:12px;image-rendering:pixelated"
HEADLINE = "margin:20px 0 4px;font-size:22px;color:#f2f2f5"
PILL = "display:inline-block;padding:4px 10px;border-radius:999px;color:#fff;font-weight:700"

_ses: Any = None


def _log(level: str, message: str, **fields: Any) -> None:
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level,
        "service": SERVICE,
        "message": message,
        **fields,
    }
    print(json.dumps(record, separators=(",", ":")))


def _client() -> Any:
    """The SES client, built once per container from the environment (region, credentials). The
    v1 API's SendRawEmail: a raw MIME message, which AWS and LocalStack both accept."""
    global _ses
    if _ses is None:
        import boto3  # provided by the Lambda runtime; imported late so tests need no AWS

        _ses = boto3.client("ses")
    return _ses


# -- the picture ---------------------------------------------------------------------------------


def _hex(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def pixels(svg: str, background: tuple[int, int, int]) -> list[list[tuple[int, int, int]]]:
    """The 24 x 24 grid of a CloudPunk SVG (only <rect> with fill and fill-opacity, as
    scripts/cloudpunks draws them) painted over ``background``."""
    grid = [[background] * GRID for _ in range(GRID)]
    for match in RECT.finditer(svg):
        attrs = dict(ATTRIBUTE.findall(match.group(1)))
        if "fill" not in attrs or "x" not in attrs:
            continue
        colour = _hex(attrs["fill"])
        alpha = float(attrs.get("fill-opacity", "1"))
        x0, y0 = int(float(attrs["x"])), int(float(attrs["y"]))
        width, height = int(float(attrs["width"])), int(float(attrs["height"]))
        for y in range(max(y0, 0), min(y0 + height, GRID)):
            for x in range(max(x0, 0), min(x0 + width, GRID)):
                under = grid[y][x]
                grid[y][x] = (
                    round(colour[0] * alpha + under[0] * (1 - alpha)),
                    round(colour[1] * alpha + under[1] * (1 - alpha)),
                    round(colour[2] * alpha + under[2] * (1 - alpha)),
                )
    return grid


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(grid: list[list[tuple[int, int, int]]], scale: int = SCALE) -> bytes:
    """An 8-bit RGB PNG of the grid, each pixel a ``scale`` x ``scale`` square (crisp edges)."""
    size = len(grid) * scale
    rows = bytearray()
    for row in grid:
        line = b"".join(bytes(pixel) * scale for pixel in row)
        rows += (b"\x00" + line) * scale  # filter type 0 (none) before every scanline
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )


# -- the message ---------------------------------------------------------------------------------


def _price(data: dict[str, Any]) -> str | None:
    amount, currency = data.get("amount"), data.get("currency")
    if amount is None or not currency:
        return None
    try:
        return f"{Decimal(str(amount)).quantize(Decimal('0.01'))} {currency}"
    except InvalidOperation:
        return None


def _when(occurred_at: str | None) -> str:
    if not occurred_at:
        return ""
    try:
        moment = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return moment.strftime("%d %b %Y, %H:%M UTC")


def _rows(kind: str, data: dict[str, Any], price: str | None) -> list[tuple[str, str]]:
    who = data.get("customer_id", "")
    rows: list[tuple[str, str]] = []
    if kind == "SALE":
        rows += [("From", data.get("counterparty") or "CloudPunks"), ("To", who)]
    elif kind in ("BID_PLACED", "BID_WITHDRAWN"):
        rows.append(("Bidder", who))
    else:
        rows.append(("Owner", who))
    if price:
        rows.append(("Price" if kind == "SALE" else "Amount", price))
    return rows


def compose(
    envelope: dict[str, Any], picture: bytes, sender: str, recipient: str, link: str | None
) -> EmailMessage:
    """The email for one activity: a plain-text part and an HTML part with the picture inline."""
    data = envelope["data"]
    kind = data["kind"]
    state, colour, subject, verb = KINDS[kind]
    number = SKU.match(data["sku"])
    name = f"CloudPunk #{number.group(1) if number else data['sku']}"
    price = _price(data)
    rows = _rows(kind, data, price)
    when = _when(envelope.get("occurred_at"))
    page = f"{link.rstrip('/')}/cloudpunks/{number.group(1)}" if link and number else None

    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject.format(name=name, price=price or "")
    message["From"] = sender
    message["To"] = recipient

    text = [f"{name} {verb}.", f"Status: {state}", *[f"{k}: {v}" for k, v in rows]]
    if when:
        text.append(f"When: {when}")
    if page:
        text.append(f"See it: {page}")
    message.set_content("\n".join(text) + "\n")

    cid = make_msgid(domain="cloudpunks.local")
    tile = "#{:02x}{:02x}{:02x}".format(*colour)
    table = "".join(
        f'<tr><td style="padding:4px 16px 4px 0;color:#8a8a93">{html.escape(k)}</td>'
        f'<td style="padding:4px 0;color:#f2f2f5"><strong>{html.escape(v)}</strong></td></tr>'
        for k, v in rows
    )
    footer = f'<p style="margin:16px 0 0;color:#8a8a93">{html.escape(when)}</p>' if when else ""
    button = (
        f'<p style="margin:20px 0 0"><a href="{html.escape(page)}" style="color:#fff;'
        f'background:#1d64c8;padding:10px 16px;border-radius:8px;text-decoration:none">'
        f"See {html.escape(name)}</a></p>"
        if page
        else ""
    )
    pill = f"{PILL};background:{tile}"
    body = (
        f'<!doctype html><html><body style="{PAGE}">'
        f'<table role="presentation" style="{CARD}"><tr><td>'
        f'<img src="cid:{cid[1:-1]}" width="240" height="240" alt="{html.escape(name)}" '
        f'style="{PICTURE}">'
        f'<h1 style="{HEADLINE}">{html.escape(name)} {html.escape(verb)}</h1>'
        f'<p style="margin:0 0 16px"><span style="{pill}">{html.escape(state)}</span></p>'
        f'<table role="presentation" style="border-collapse:collapse">{table}</table>'
        f"{footer}{button}</td></tr></table></body></html>\n"
    )
    message.add_alternative(body, subtype="html")
    html_part = message.get_body(preferencelist=("html",))
    if html_part is None:  # pragma: no cover - added on the line above
        raise RuntimeError("the HTML part is missing")
    html_part.add_related(picture, maintype="image", subtype="png", cid=cid)
    return message


# -- the handler ---------------------------------------------------------------------------------


def art_for(sku: str) -> str | None:
    number = SKU.match(sku)
    if number is None:
        return None
    path = ART / f"{number.group(1)}.svg"
    return path.read_text() if path.is_file() else None


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    envelope = event.get("detail") if isinstance(event, dict) else None
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(envelope, dict) or not isinstance(data, dict):
        _log("error", "malformed_event")
        return {"sent": False, "reason": "malformed"}
    fields = {
        "event_id": envelope.get("event_id"),
        "correlation_id": envelope.get("correlation_id"),
    }
    kind, sku = data.get("kind"), data.get("sku")
    if kind not in KINDS or not isinstance(sku, str):
        _log("info", "activity_skipped", reason="unknown kind or sku", kind=kind, **fields)
        return {"sent": False, "reason": "skipped"}
    svg = art_for(sku)
    if svg is None:
        _log("info", "activity_skipped", reason="no art for this sku", sku=sku, **fields)
        return {"sent": False, "reason": "skipped"}
    sender, recipient = os.environ.get("EMAIL_FROM", ""), os.environ.get("EMAIL_TO", "")
    if not sender or not recipient:
        _log("error", "email_not_configured", **fields)
        return {"sent": False, "reason": "not configured"}

    message = compose(
        envelope,
        png(pixels(svg, KINDS[kind][1])),
        sender,
        recipient,
        os.environ.get("STOREFRONT_URL") or None,
    )
    response = _client().send_raw_email(
        Source=sender,
        Destinations=[recipient],
        RawMessage={"Data": message.as_bytes()},
    )
    _log(
        "info",
        "activity_emailed",
        kind=kind,
        sku=sku,
        message_id=response.get("MessageId"),
        **fields,
    )
    return {"sent": True}

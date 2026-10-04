"""market-activity-email: the picture, the message and the handler, with a fake SES client."""

import email
import struct
import sys
import zlib
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import handler

COLLECTION = Path(__file__).resolve().parents[3] / "nft-collection"


@pytest.fixture(autouse=True)
def _art_and_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # In the package the art sits next to the handler; here it is read from its source.
    monkeypatch.setattr(handler, "ART", COLLECTION)
    monkeypatch.setenv("EMAIL_FROM", "owner@example.com")
    monkeypatch.setenv("EMAIL_TO", "owner@example.com")
    monkeypatch.delenv("STOREFRONT_URL", raising=False)


class FakeSes:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._error = error

    def send_raw_email(self, **request: Any) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        self.sent.append(request)
        return {"MessageId": "m-1"}


@pytest.fixture
def ses(monkeypatch: pytest.MonkeyPatch) -> FakeSes:
    fake = FakeSes()
    monkeypatch.setattr(handler, "_client", lambda: fake)
    return fake


def envelope(kind: str = "SALE", sku: str = "CP-0023", **data: Any) -> dict[str, Any]:
    payload = {"kind": kind, "sku": sku, "customer_id": "bob"} | data
    return {
        "event_id": "01J9Z6Q4W8K3M2N1P0R7S5T4V3",
        "event_type": "MarketActivity",
        "occurred_at": "2026-10-04T06:30:00.000Z",
        "correlation_id": "corr-1",
        "data": payload,
    }


def decode_png(blob: bytes) -> tuple[int, int, list[bytes]]:
    """Width, height and the raw RGB scanlines of an unfiltered 8-bit RGB PNG."""
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    position, idat, width, height = 8, b"", 0, 0
    while position < len(blob):
        (length,) = struct.unpack(">I", blob[position : position + 4])
        kind = blob[position + 4 : position + 8]
        data = blob[position + 8 : position + 8 + length]
        (crc,) = struct.unpack(">I", blob[position + 8 + length : position + 12 + length])
        assert crc == zlib.crc32(kind + data), kind
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", data[:10])
            assert (depth, colour) == (8, 2)
        elif kind == b"IDAT":
            idat += data
        position += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + width * 3
    rows = [raw[i * stride : (i + 1) * stride] for i in range(height)]
    assert all(row[0] == 0 for row in rows)
    return width, height, [row[1:] for row in rows]


def pixel(rows: list[bytes], x: int, y: int) -> tuple[int, ...]:
    return tuple(rows[y][x * 3 : x * 3 + 3])


# -- the picture ---------------------------------------------------------------------------------


def test_the_picture_is_the_art_scaled_up_on_the_state_colour() -> None:
    svg = (COLLECTION / "0001.svg").read_text()  # its first pixel: black at (11, 1)
    width, height, rows = decode_png(handler.png(handler.pixels(svg, handler.BID)))

    assert (width, height) == (240, 240)
    assert pixel(rows, 0, 0) == handler.BID  # the background
    assert pixel(rows, 11 * 10, 1 * 10) == (0, 0, 0)
    assert pixel(rows, 11 * 10 + 9, 1 * 10 + 9) == (0, 0, 0)  # one art pixel is 10 x 10


def test_fill_opacity_blends_over_what_is_underneath() -> None:
    svg = '<rect x="0" y="0" width="2" height="1" fill="#ffffff" fill-opacity="0.5"/>'
    grid = handler.pixels(svg, (0, 0, 0))
    assert grid[0][0] == grid[0][1] == (128, 128, 128)
    assert grid[0][2] == (0, 0, 0)


def test_every_cloudpunk_draws() -> None:
    svgs = sorted(COLLECTION.glob("*.svg"))
    assert len(svgs) == 100
    for path in svgs:
        grid = handler.pixels(path.read_text(), handler.OWNED)
        assert any(cell != handler.OWNED for row in grid for cell in row), path.name


# -- the message ---------------------------------------------------------------------------------


def parts(message: Message) -> dict[str, Message]:
    return {part.get_content_type(): part for part in message.walk()}


@pytest.mark.parametrize(
    ("kind", "data", "subject", "state"),
    [
        ("LISTED", {}, "CloudPunk #0023 is up for bid", "Up for bid"),
        ("UNLISTED", {}, "CloudPunk #0023 was taken off the market", "Owned"),
        (
            "BID_PLACED",
            {"amount": "12.5", "currency": "ETH"},
            "New bid on CloudPunk #0023: 12.50 ETH",
            "Up for bid",
        ),
        (
            "BID_WITHDRAWN",
            {"amount": "12.50", "currency": "ETH"},
            "Bid withdrawn on CloudPunk #0023",
            "Up for bid",
        ),
        (
            "SALE",
            {"amount": "30", "currency": "ETH"},
            "CloudPunk #0023 sold for 30.00 ETH",
            "Owned",
        ),
    ],
)
def test_each_kind_has_its_subject_and_status(
    kind: str, data: dict[str, Any], subject: str, state: str
) -> None:
    message = handler.compose(
        envelope(kind, **data), b"png", "a@example.com", "b@example.com", None
    )

    assert message["Subject"] == subject
    found = parts(message)
    assert f"Status: {state}" in found["text/plain"].get_content()
    assert f">{state}</span>" in found["text/html"].get_content()


def test_a_sale_says_from_whom_and_the_picture_is_inline() -> None:
    message = handler.compose(
        envelope("SALE", counterparty="alice", amount="30.00", currency="ETH"),
        b"\x89PNG-bytes",
        "a@example.com",
        "b@example.com",
        "http://shop.example/",
    )
    found = parts(message)
    text = found["text/plain"].get_content()
    page = found["text/html"].get_content()
    image = found["image/png"]

    assert "From: alice" in text
    assert "To: bob" in text
    assert "Price: 30.00 ETH" in text
    assert "When: 04 Oct 2026, 06:30 UTC" in text
    assert "See it: http://shop.example/cloudpunks/0023" in text
    assert image.get_payload(decode=True) == b"\x89PNG-bytes"
    cid = image["Content-ID"].strip("<>")
    assert f'src="cid:{cid}"' in page
    assert 'href="http://shop.example/cloudpunks/0023"' in page


def test_a_sale_from_cloudpunks_and_everything_shown_is_escaped() -> None:
    message = handler.compose(
        envelope("SALE", customer_id="<b>bob</b>", amount="1", currency="ETH"),
        b"png",
        "a@example.com",
        "b@example.com",
        None,
    )
    page = parts(message)["text/html"].get_content()
    assert "From: CloudPunks" in parts(message)["text/plain"].get_content()
    assert "<b>bob</b>" not in page
    assert "&lt;b&gt;bob&lt;/b&gt;" in page


# -- the handler ---------------------------------------------------------------------------------


def test_the_handler_sends_one_raw_email_to_the_configured_address(ses: FakeSes) -> None:
    result = handler.lambda_handler(
        {"detail": envelope("BID_PLACED", amount="12.50", currency="ETH")}, None
    )

    assert result == {"sent": True}
    [request] = ses.sent
    assert request["Source"] == "owner@example.com"
    assert request["Destinations"] == ["owner@example.com"]
    sent = email.message_from_bytes(request["RawMessage"]["Data"])
    assert sent["Subject"] == "New bid on CloudPunk #0023: 12.50 ETH"
    image = next(p for p in sent.walk() if p.get_content_type() == "image/png")
    width, _, _ = decode_png(image.get_payload(decode=True))
    assert width == 240


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"detail": "nope"},
        {"detail": {"data": None}},
        {"detail": envelope("OFFER_EXPIRED")},  # a kind added later: not ours to send
        {"detail": envelope(sku="E2E-ABC")},  # not a CloudPunk (the cloud suite's item)
        {"detail": envelope(sku="CP-0999")},  # no art
    ],
)
def test_what_can_never_be_sent_is_dropped_not_retried(event: dict[str, Any], ses: FakeSes) -> None:
    assert handler.lambda_handler(event, None)["sent"] is False
    assert ses.sent == []


def test_without_an_address_nothing_is_sent(ses: FakeSes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMAIL_TO")
    assert handler.lambda_handler({"detail": envelope()}, None) == {
        "sent": False,
        "reason": "not configured",
    }
    assert ses.sent == []


def test_an_ses_error_is_raised_so_the_invoke_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handler, "_client", lambda: FakeSes(error=RuntimeError("throttled")))
    with pytest.raises(RuntimeError, match="throttled"):
        handler.lambda_handler({"detail": envelope()}, None)


def test_the_address_is_never_logged(ses: FakeSes, capsys: pytest.CaptureFixture[str]) -> None:
    handler.lambda_handler({"detail": envelope()}, None)
    assert "owner@example.com" not in capsys.readouterr().out

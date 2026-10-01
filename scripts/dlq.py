"""Inspect and redrive a dead-letter queue (DESIGN.md section 11, poison-message drill).

    make dlq-peek q=inventory-order-events-dlq
    make dlq-redrive q=inventory-order-events-dlq

``peek`` lists what is in the DLQ without taking it: messages are received with a visibility
timeout of 0 and never deleted. ``redrive`` sends each message back to the queue it came from
(the DLQ's name without ``-dlq``) and then deletes it. Do that after the cause is fixed: a
message that is still poison goes round the loop again and returns here after five receives.

A local tool: the Make targets point it at LocalStack through the environment (endpoint, dummy
credentials, no profile). The client itself is built from the environment only.
"""

import argparse
import sys
from typing import Any

import boto3

DLQ_SUFFIX = "-dlq"
BODY_LIMIT = 2000
MAX_PEEK = 100


def source_queue(dlq_name: str) -> str:
    if not dlq_name.endswith(DLQ_SUFFIX):
        raise SystemExit(f"{dlq_name!r} is not a dead-letter queue (its name must end in -dlq)")
    return dlq_name.removesuffix(DLQ_SUFFIX)


def peek(sqs: Any, dlq_name: str, limit: int = MAX_PEEK) -> list[dict[str, Any]]:
    """Up to ``limit`` distinct messages, left in the queue and visible to others."""
    url = sqs.get_queue_url(QueueName=dlq_name)["QueueUrl"]
    seen: dict[str, dict[str, Any]] = {}
    for _ in range(limit):  # visibility 0 can hand back the same message, so bound the loop
        response = sqs.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=10,
            VisibilityTimeout=0,
            WaitTimeSeconds=0,
            AttributeNames=["All"],
        )
        batch = response.get("Messages", [])
        new = [m for m in batch if m["MessageId"] not in seen]
        if not new:
            break
        for message in new:
            seen[message["MessageId"]] = message
        if len(seen) >= limit:
            break
    return list(seen.values())[:limit]


def redrive(sqs: Any, dlq_name: str) -> int:
    """Move every message back to its source queue. Returns how many were moved."""
    destination = sqs.get_queue_url(QueueName=source_queue(dlq_name))["QueueUrl"]
    url = sqs.get_queue_url(QueueName=dlq_name)["QueueUrl"]
    moved = 0
    while True:
        batch = sqs.receive_message(
            QueueUrl=url, MaxNumberOfMessages=10, VisibilityTimeout=30, WaitTimeSeconds=0
        ).get("Messages", [])
        if not batch:
            return moved
        for message in batch:
            # Send first, delete second: a crash between the two duplicates the message, which
            # every consumer tolerates (idempotent on event_id), and never loses it.
            sqs.send_message(QueueUrl=destination, MessageBody=message["Body"])
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
            moved += 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["peek", "redrive"])
    parser.add_argument("queue", help="the dead-letter queue, e.g. inventory-order-events-dlq")
    args = parser.parse_args(argv)
    sqs = boto3.client("sqs")

    if args.command == "redrive":
        print(f"redrove {redrive(sqs, args.queue)} message(s) to {source_queue(args.queue)}")
        return 0

    messages = peek(sqs, args.queue)
    print(f"{len(messages)} message(s) in {args.queue}")
    for message in messages:
        attributes = message.get("Attributes", {})
        print(
            f"--- {message['MessageId']} received {attributes.get('ApproximateReceiveCount', '?')}x"
        )
        print(message["Body"][:BODY_LIMIT])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

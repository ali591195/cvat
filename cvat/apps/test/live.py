# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import asyncio
import json
from urllib.parse import parse_qs

from django.conf import settings
from django.core import signing
from redis.asyncio import Redis

TICKET_SALT = "label-counts-live"
TICKET_MAX_AGE = 60
CLOSE_UNAUTHORIZED = 4401


def get_channel(task_id: int) -> str:
    return f"label_counts:task:{task_id}"


def make_ticket(user_id: int, task_id: int) -> str:
    return signing.dumps({"user_id": user_id, "task_id": task_id}, salt=TICKET_SALT)


def read_ticket(ticket: str) -> dict | None:
    "Returns the ticket payload, or None if the ticket is forged or older than TICKET_MAX_AGE"
    try:
        return signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
    except signing.BadSignature:
        return None


async def _forward_changes(pubsub, send, task_id: int):
    async for message in pubsub.listen():
        if message["type"] == "message":
            await send(
                {
                    "type": "websocket.send",
                    "text": json.dumps({"type": "changed", "task_id": task_id}),
                }
            )


async def _wait_for_disconnect(receive):
    while (await receive())["type"] != "websocket.disconnect":
        pass


async def live_label_counts(scope, receive, send):
    """
    ASGI handler for WS /api/label-counts/live?ticket=...
    Tells the client each time annotations of the ticket's task change.
    The ticket is signed and short-lived, so no database access is needed to check it.
    """
    await receive()  # websocket.connect
    await send({"type": "websocket.accept"})

    query = parse_qs(scope["query_string"].decode())
    ticket = read_ticket(query.get("ticket", [""])[0])
    if ticket is None:
        await send({"type": "websocket.close", "code": CLOSE_UNAUTHORIZED})
        return

    task_id = ticket["task_id"]
    redis_settings = settings.REDIS_INMEM_SETTINGS
    redis = Redis(
        host=redis_settings["HOST"],
        port=redis_settings["PORT"],
        db=redis_settings["DB"],
        password=redis_settings["PASSWORD"],
    )
    async with redis.pubsub() as pubsub:
        await pubsub.subscribe(get_channel(task_id))

        forwarding = asyncio.create_task(_forward_changes(pubsub, send, task_id))
        disconnected = asyncio.create_task(_wait_for_disconnect(receive))
        _, pending = await asyncio.wait(
            [forwarding, disconnected], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()

    await redis.aclose()

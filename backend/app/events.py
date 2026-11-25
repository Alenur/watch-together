import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

import psycopg
from sqlalchemy import URL, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
CHANNEL = "watch_together_events"


async def publish(db: AsyncSession, topic: str, data: dict) -> None:
    # PostgreSQL delivers NOTIFY only after this transaction commits.
    payload = json.dumps({"topic": topic, "data": data}, ensure_ascii=False)
    await db.execute(select(func.pg_notify(CHANNEL, payload)))


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[dict | None] = field(default_factory=lambda: asyncio.Queue(maxsize=128))
    active: bool = True

    def put(self, event: dict) -> None:
        if not self.active:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.close()

    def close(self) -> None:
        if self.active:
            self.active = False
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(None)


class EventListener:
    def __init__(self, database_url: URL):
        self.dsn = database_url.set(drivername="postgresql").render_as_string(hide_password=False)
        self.ready = asyncio.Event()
        self.subscribers: dict[str, set[Subscription]] = defaultdict(set)

    def subscribe(self, *topics: str) -> Subscription:
        subscription = Subscription()
        for topic in topics:
            self.subscribers[topic].add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription, *topics: str) -> None:
        subscription.close()
        for topic in topics:
            self.subscribers[topic].discard(subscription)
            if not self.subscribers[topic]:
                del self.subscribers[topic]

    async def run(self) -> None:
        while True:
            try:
                connection = await psycopg.AsyncConnection.connect(
                    self.dsn, autocommit=True, connect_timeout=5
                )
                async with connection:
                    await connection.execute(f"LISTEN {CHANNEL}")
                    self.ready.set()
                    async for notification in connection.notifies():
                        event = json.loads(notification.payload)
                        for subscription in self.subscribers.get(event["topic"], ()):
                            subscription.put(event["data"])
            except (psycopg.Error, OSError, ValueError):
                logger.warning("PostgreSQL event stream interrupted. Reconnecting.", exc_info=True)
            finally:
                self.ready.clear()
                for subscriptions in self.subscribers.values():
                    for subscription in subscriptions:
                        subscription.close()
            await asyncio.sleep(1)

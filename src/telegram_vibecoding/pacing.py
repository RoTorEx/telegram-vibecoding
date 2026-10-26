"""One chat-wide write budget, including SDK-generated edits and cleanup."""

import asyncio
import logging
import math
import time
from typing import cast

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import AnswerCallbackQuery, Response, TelegramMethod
from aiogram.methods.base import TelegramType

from telegram_vibecoding.store import BotStore

log = logging.getLogger(__name__)


class ChatPacer(BaseRequestMiddleware):
    def __init__(self, store: BotStore, owner: int):
        self.store, self.owner = store, owner
        # One private-chat write per second, shared by sends, edits and deletes.
        self.interval = 1.05
        self.acknowledged: dict[str, None] = {}
        self.last_write = 0.0
        self.lock = asyncio.Lock()

    @property
    def remaining(self) -> float:
        return max(0, float(self.store.get("telegram_retry_until", "0")) - time.time())

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if isinstance(method, AnswerCallbackQuery):
            cid = method.callback_query_id
            if cid in self.acknowledged:
                return cast(Response[TelegramType], True)
            self.acknowledged[cid] = None
            if len(self.acknowledged) > 512:
                self.acknowledged.pop(next(iter(self.acknowledged)))
            try:
                return await make_request(bot, cast(TelegramMethod[TelegramType], method))
            except BaseException:
                self.acknowledged.pop(cid, None)
                raise
        if getattr(method, "chat_id", None) != self.owner or method.__api_method__.startswith("get"):
            return await make_request(bot, method)
        async with self.lock:
            remaining = self.remaining
            if remaining > 0:
                raise TelegramRetryAfter(
                    method=method, message="Persisted Telegram cooldown", retry_after=math.ceil(remaining)
                )
            await asyncio.sleep(max(0, self.last_write + self.interval - time.monotonic()))
            self.last_write = time.monotonic()
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as exc:
                self.store.set("telegram_retry_until", str(time.time() + exc.retry_after))
                log.warning(
                    "Telegram chat writes paused for %s seconds; input and queues retained", exc.retry_after
                )
                raise

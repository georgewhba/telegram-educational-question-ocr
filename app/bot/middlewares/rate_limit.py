"""In-memory sliding window rate limiter middleware for Telegram updates."""

import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.config.settings import Settings, get_settings


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or get_settings()
        # Maps user_id -> list of timestamps
        self.user_requests: dict[int, list[float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.time()
        window = self.settings.RATE_LIMIT_WINDOW_SECONDS
        max_requests = self.settings.RATE_LIMIT_REQUESTS

        # Bypass rate limiter for admins
        if user_id in self.settings.admin_user_ids:
            return await handler(event, data)

        # Get existing timestamps and clean up expired ones
        timestamps = self.user_requests.get(user_id, [])
        timestamps = [t for t in timestamps if now - t < window]

        if len(timestamps) >= max_requests:
            await event.answer("⚠️ يرجى الانتظار قليلًا قبل إرسال طلب آخر لتفادي الضغط على النظام.")
            return None

        timestamps.append(now)
        self.user_requests[user_id] = timestamps
        return await handler(event, data)

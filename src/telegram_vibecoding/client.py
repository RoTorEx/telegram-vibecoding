"""Versioned Core HTTP/Unix client; no backend implementation dependency."""

from aiohttp import ClientSession, ClientTimeout, UnixConnector

from telegram_vibecoding.config import Settings


class CoreClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.http: ClientSession | None = None

    async def call(self, path: str, body: dict | None = None):
        if self.http is None:
            self.http = ClientSession(
                connector=UnixConnector(path=str(self.settings.socket)), timeout=ClientTimeout(total=90)
            )
        async with self.http.request(
            "POST" if body is not None else "GET", "http://engine" + path, json=body
        ) as r:
            if r.status == 404:
                raise ValueError("Core endpoint is unavailable in the running version")
            value = await r.json()
            if r.status >= 500:
                raise ConnectionError(value.get("error", "Engine temporarily unavailable"))
            if r.status >= 400:
                raise ValueError(value.get("error", f"Engine returned {r.status}"))
            return value

    async def close(self):
        if self.http:
            await self.http.close()

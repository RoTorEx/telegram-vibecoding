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


class SessionActionsClient:
    """Cancel frontend transfers before authorized native Stop/Archive."""

    def __init__(self, client, cancel_inputs):
        self.client, self.cancel_inputs = client, cancel_inputs

    async def call(self, path: str, body: dict | None = None):
        parts = path.strip("/").split("/")
        if (
            body is not None
            and len(parts) == 3
            and parts[0] == "sessions"
            and parts[2] in {"stop", "archive"}
        ):
            await self.cancel_inputs(parts[1])
        return await self.client.call(path, body)

    async def close(self):
        await self.client.close()

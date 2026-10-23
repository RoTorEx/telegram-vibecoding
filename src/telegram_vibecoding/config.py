"""Private Telegram configuration, independent of the Core implementation."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    runtime_dir: Path
    token_file: Path
    allowed_user_id: int = 0
    host_id: str = "vps"
    bot_username: str = ""

    @property
    def socket(self) -> Path:
        return self.runtime_dir / "engine.sock"

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = (
            path
            or Path(
                os.environ.get("TELEGRAM_VIBECODING_CONFIG", "~/.config/remote-vibecoding/bot.toml")
            ).expanduser()
        )
        values = tomllib.loads(path.read_text()) if path.exists() else {}
        if unknown := set(values) - set(cls.__dataclass_fields__):
            raise ValueError(f"Unknown Telegram configuration keys: {', '.join(sorted(unknown))}")
        data = Path(values.pop("data_dir", "~/.local/state/remote-vibecoding")).expanduser()
        runtime = Path(values.pop("runtime_dir", str(data / "run"))).expanduser()
        token = Path(values.pop("token_file", "~/.config/remote-vibecoding/bot-token")).expanduser()
        return cls(data_dir=data, runtime_dir=runtime, token_file=token, **values)

    def prepare(self) -> None:
        for path in [self.data_dir, self.runtime_dir, self.data_dir / "uploads"]:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        if len(os.fsencode(self.socket)) > 100:
            raise ValueError("runtime_dir is too long for a portable Unix socket")

    def read_token(self) -> str:
        if self.allowed_user_id <= 0:
            raise ValueError("Configure allowed_user_id before starting the bot")
        if self.token_file.stat().st_mode & 0o077:
            raise ValueError("The bot token file must have mode 600")
        token = self.token_file.read_text().strip()
        if ":" not in token or any(c.isspace() for c in token):
            raise ValueError("Invalid bot token file")
        return token

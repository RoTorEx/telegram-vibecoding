"""Device enrollment and one-request authorization, separate from native approvals.

Telegram biometrics unlock an exportable device secret. HMAC proves possession
of that secret; it is not hardware attestation of a fresh biometric scan.
"""

import hashlib
import hmac
import json
import secrets
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from aiohttp import web

from telegram_vibecoding.store import BotStore

# Ten minutes permits reviewing a recording, without an indefinitely usable approval.
REQUEST_TTL = 600
# A fresh proof is short lived even when its parent request remains pending.
PROOF_TTL = 60
# Enrollment is an explicit, one-use administrative operation, never a Telegram recovery flow.
ENROLL_TTL = 600
INIT_TTL = 300


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ConfirmationRequired(ValueError):
    def __init__(self):
        super().__init__("Confirmation required. Open the confirmation button before this request can run.")


class Confirmations:
    def __init__(self, store: BotStore):
        self.store = store
        self.grant: ContextVar[bool] = ContextVar("confirmed_request", default=False)
        self.source: ContextVar[str] = ContextVar("confirmation_source", default="")
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS auth_devices(
                id TEXT PRIMARY KEY, secret TEXT NOT NULL, created REAL NOT NULL, revoked REAL);
            CREATE TABLE IF NOT EXISTS auth_enrollment(
                hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_actions(
                id TEXT PRIMARY KEY, source TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                payload TEXT NOT NULL, digest TEXT NOT NULL, created REAL NOT NULL,
                expires REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                device_id TEXT, notice_id INTEGER);
            CREATE TABLE IF NOT EXISTS auth_inbox(
                inbox_id INTEGER PRIMARY KEY, action_id TEXT NOT NULL REFERENCES auth_actions(id));
            CREATE TABLE IF NOT EXISTS auth_proofs(
                id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES auth_actions(id),
                device_id TEXT NOT NULL, challenge TEXT NOT NULL, expires REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0);
        """)

    def enrollment(self) -> str:
        code = secrets.token_urlsafe(32)
        with self.store.db:
            self.store.db.execute("DELETE FROM auth_enrollment")
            self.store.db.execute(
                "INSERT INTO auth_enrollment VALUES(?,?)",
                (hashlib.sha256(code.encode()).hexdigest(), time.time() + ENROLL_TTL),
            )
        return code

    def enroll(self, code: str, device: str) -> str:
        if not device or len(device) > 256:
            raise ValueError("Invalid device identifier")
        key = secrets.token_hex(32)
        with self.store.db:
            row = self.store.one(
                "SELECT * FROM auth_enrollment WHERE hash=?", (hashlib.sha256(code.encode()).hexdigest(),)
            )
            if not row or row["expires"] < time.time():
                raise ValueError("Enrollment code is invalid or expired. Obtain a new code through SSH.")
            if self.store.one("SELECT 1 FROM auth_devices WHERE id=? AND revoked IS NULL", (device,)):
                raise ValueError(
                    "This device is already enrolled. Revoke it through SSH before replacing its key."
                )
            self.store.db.execute("DELETE FROM auth_enrollment")
            self.store.db.execute(
                "INSERT INTO auth_devices VALUES(?,?,?,NULL) ON CONFLICT(id) DO UPDATE "
                "SET secret=excluded.secret,created=excluded.created,revoked=NULL",
                (device, key, time.time()),
            )
        return key

    def revoke(self, device: str) -> None:
        with self.store.db:
            self.store.db.execute(
                "UPDATE auth_devices SET revoked=?,secret='' WHERE id=?", (time.time(), device)
            )
            self.store.db.execute(
                "UPDATE auth_actions SET status='cancelled' WHERE device_id=? AND status='approved'",
                (device,),
            )
            self.store.db.execute(
                "UPDATE inbox SET status='done' WHERE id IN (SELECT inbox_id FROM auth_inbox JOIN auth_actions ON auth_actions.id=action_id WHERE auth_actions.status='cancelled')"
            )

    def stage(self, source: str, kind: str, payload: dict) -> dict:
        existing = self.store.one("SELECT * FROM auth_actions WHERE source=?", (source,))
        if existing:
            if existing["digest"] != digest(payload):
                raise ValueError("The captured request changed; it cannot reuse its confirmation.")
            return existing
        now = time.time()
        count = self.store.one("SELECT COUNT(*) AS n FROM auth_actions WHERE status='pending'")
        if count and count["n"] >= 100:
            raise ValueError("Too many requests await confirmation. Confirm or wait for them to expire.")
        aid = secrets.token_hex(16)
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO auth_actions(id,source,kind,payload,digest,created,expires) VALUES(?,?,?,?,?,?,?)",
                (aid, source, kind, canonical(payload), digest(payload), now, now + REQUEST_TTL),
            )
        return self.action(aid)

    def action(self, aid: str) -> dict:
        row = self.store.one("SELECT * FROM auth_actions WHERE id=?", (aid,))
        if not row or row["digest"] != digest(json.loads(row["payload"])):
            raise ValueError("Request is unavailable or changed")
        return row

    def stage_input(self, rows: list[dict], context: dict) -> dict:
        payload = {
            "rows": [{k: r[k] for k in ("id", "body", "session_id", "mode")} for r in rows],
            "context": context,
        }
        action = self.stage("input:" + ",".join(str(r["id"]) for r in rows), "input", payload)
        with self.store.db:
            for row in rows:
                self.store.db.execute(
                    "INSERT OR IGNORE INTO auth_inbox VALUES(?,?)", (row["id"], action["id"])
                )
                self.store.db.execute("UPDATE inbox SET status='auth_pending' WHERE id=?", (row["id"],))
        return action

    def input_action(self, rows: list[dict]) -> dict | None:
        links = [
            self.store.one("SELECT action_id FROM auth_inbox WHERE inbox_id=?", (r["id"],)) for r in rows
        ]
        if not any(links):
            return None
        if not all(links) or len({r["action_id"] for r in links if r}) != 1:
            raise ValueError("The media group changed. Send it again for a new confirmation.")
        first = next(link for link in links if link)
        action = self.action(first["action_id"])
        captured = json.loads(action["payload"])["rows"]
        if [(r["id"], r["body"]) for r in captured] != [(r["id"], r["body"]) for r in rows]:
            raise ValueError("The captured input changed")
        # Auto-created sessions update the working row; original body/path stays immutable.
        for original, current in zip(captured, rows, strict=True):
            if not json.loads(original["body"]).get("_relay", {}).get("new_session_path"):
                if (original["session_id"], original["mode"]) != (current["session_id"], current["mode"]):
                    raise ValueError("The captured target changed")
        return action

    def proof(self, aid: str, device: str, *, decision="approve") -> dict:
        action = self.action(aid)
        if action["status"] != "pending" or action["expires"] <= time.time():
            raise ValueError("Request has already been handled or expired")
        if not self.store.one("SELECT 1 FROM auth_devices WHERE id=? AND revoked IS NULL", (device,)):
            raise ValueError("This phone is not enrolled. Use an enrollment code obtained through SSH.")
        if decision not in {"approve", "cancel"}:
            raise ValueError("Invalid decision")
        pid = secrets.token_hex(16)
        challenge = canonical(
            {
                "v": 1,
                "proof": pid,
                "request": aid,
                "digest": action["digest"],
                "device": device,
                "decision": decision,
            }
        )
        expires = min(action["expires"], time.time() + PROOF_TTL)
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO auth_proofs(id,action_id,device_id,challenge,expires) VALUES(?,?,?,?,?)",
                (pid, aid, device, challenge, expires),
            )
        return {"proof": pid, "challenge": challenge, "expires": expires}

    def confirm(self, pid: str, signature: str) -> str:
        with self.store.db:
            proof = self.store.one("SELECT * FROM auth_proofs WHERE id=?", (pid,))
            if not proof or proof["used"] or proof["expires"] <= time.time():
                raise ValueError("Confirmation expired or already used")
            action = self.action(proof["action_id"])
            signed = json.loads(proof["challenge"])
            if (
                signed["digest"] != action["digest"]
                or signed["request"] != action["id"]
                or signed["device"] != proof["device_id"]
            ):
                raise ValueError("The signed request changed")
            device = self.store.one(
                "SELECT * FROM auth_devices WHERE id=? AND revoked IS NULL", (proof["device_id"],)
            )
            if not device or action["status"] != "pending" or action["expires"] <= time.time():
                raise ValueError("Request or device is no longer authorized")
            expected = hmac.new(
                bytes.fromhex(device["secret"]), proof["challenge"].encode(), "sha256"
            ).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError("Invalid device proof")
            decision = json.loads(proof["challenge"])["decision"]
            status = "approved" if decision == "approve" else "cancelled"
            self.store.db.execute("UPDATE auth_proofs SET used=1 WHERE id=?", (pid,))
            self.store.db.execute(
                "UPDATE auth_actions SET status=?,device_id=? WHERE id=?",
                (status, device["id"], action["id"]),
            )
            if action["kind"] == "input":
                self.store.db.execute(
                    "UPDATE inbox SET status=? WHERE id IN (SELECT inbox_id FROM auth_inbox WHERE action_id=?)",
                    ("pending" if status == "approved" else "done", action["id"]),
                )
        return status

    def expire(self) -> None:
        with self.store.db:
            self.store.db.execute(
                "UPDATE auth_actions SET status='expired' WHERE status='pending' AND expires<=?",
                (time.time(),),
            )
            self.store.db.execute(
                "UPDATE inbox SET status='done' WHERE status='auth_pending' AND id IN "
                "(SELECT inbox_id FROM auth_inbox JOIN auth_actions ON auth_actions.id=action_id WHERE auth_actions.status IN ('expired','cancelled'))"
            )
            self.store.db.execute("DELETE FROM auth_proofs WHERE expires<=?", (time.time(),))
            self.store.db.execute("DELETE FROM auth_enrollment WHERE expires<=?", (time.time(),))
            cutoff = time.time() - 7 * 86400
            for table in ("auth_proofs", "auth_inbox"):
                self.store.db.execute(
                    f"DELETE FROM {table} WHERE action_id IN (SELECT id FROM auth_actions WHERE created<=? AND status NOT IN ('pending','approved','dispatching'))",
                    (cutoff,),
                )
            self.store.db.execute(
                "DELETE FROM auth_actions WHERE created<=? AND status NOT IN ('pending','approved','dispatching')",
                (cutoff,),
            )

    def completed(self, aid: str, status="done") -> None:
        with self.store.db:
            self.store.db.execute("UPDATE auth_actions SET status=? WHERE id=?", (status, aid))


class GuardedClient:
    def __init__(self, client, auth: Confirmations):
        self.client, self.auth = client, auth

    async def call(self, path: str, body: dict | None = None):
        if body is not None and not self.auth.grant.get():
            source = self.auth.source.get()
            if not source:
                raise ValueError("A Core mutation requires a captured user request")
            labels = {
                "stop": "Stop session",
                "archive": "Archive session",
                "reopen": "Reopen session",
                "rename": "Rename session",
                "settings": "Change session settings",
            }
            payload = {
                "path": path,
                "body": body,
                "label": labels.get(path.rsplit("/", 1)[-1], "Apply agent action"),
            }
            if path == "/sessions":
                payload["label"] = "Create session"
                payload["target"] = {"cwd": body.get("cwd", "")}
            elif path.startswith("/sessions/"):
                sid = path.split("/")[2]
                session = await self.client.call(f"/sessions/{sid}")
                payload["target"] = {k: session.get(k) for k in ("id", "name", "cwd")}
            elif path.startswith("/questions/"):
                payload["label"] = "Answer agent question"
            self.auth.stage(source + ":" + path, "operation", payload)
            raise ConfirmationRequired()
        return await self.client.call(path, body)

    async def close(self):
        await self.client.close()


def validate_init_data(raw: str, token: str, owner: int, now: float | None = None) -> None:
    try:
        fields = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=30)
        values = dict(fields)
        if len(values) != len(fields):
            raise ValueError("Duplicate fields")
        received = values.pop("hash")
        key = hmac.new(b"WebAppData", token.encode(), "sha256").digest()
        expected = hmac.new(
            key, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), "sha256"
        ).hexdigest()
        age = (time.time() if now is None else now) - int(values["auth_date"])
        user = json.loads(values["user"])
        if not hmac.compare_digest(expected, received) or not -30 <= age <= INIT_TTL or user["id"] != owner:
            raise ValueError("Untrusted Telegram data")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Open this confirmation from a fresh bot button in Telegram") from exc


def application(runtime) -> web.Application:
    auth = runtime.confirmations
    settings = runtime.settings
    base = urlsplit(settings.confirmation_url)
    origin = f"{base.scheme}://{base.netloc}"
    prefix = base.path.rstrip("/")
    assets = Path(__file__).parent / "miniapp"
    attempts: dict[str, tuple[float, int]] = {}

    @web.middleware
    async def boundaries(request, handler):
        try:
            if request.method == "POST":
                if request.headers.get("Origin") != origin or request.content_type != "application/json":
                    raise web.HTTPForbidden(text="Invalid request origin or content type")
                raw = request.headers.get("X-Telegram-Init-Data", "")
                validate_init_data(raw, settings.read_token(), settings.allowed_user_id)
                # A global bound also covers clients sharing a proxy address.
                bucket = "enroll" if request.path.endswith("/enroll") else "api"
                started, count = attempts.get(bucket, (time.monotonic(), 0))
                if time.monotonic() - started > 60:
                    started, count = time.monotonic(), 0
                if count >= (5 if bucket == "enroll" else 120):
                    raise web.HTTPTooManyRequests(text="Try again later")
                attempts[bucket] = (started, count + 1)
            response = await handler(request)
        except (ValueError, KeyError, TypeError):
            response = web.json_response(
                {
                    "error": "Request unavailable, expired, or unauthorized. Reopen the bot button; new devices require an SSH enrollment code."
                },
                status=403,
            )
        except web.HTTPException as exc:
            response = web.json_response({"error": exc.reason}, status=exc.status)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; script-src 'self' https://telegram.org; style-src 'self'; connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org",
            }
        )
        return response

    app = web.Application(middlewares=[boundaries], client_max_size=16 * 1024)

    async def asset(request):
        name = request.match_info.get("asset", "index.html")
        if name not in {"index.html", "app.js", "style.css"}:
            raise web.HTTPNotFound()
        return web.Response(
            body=(assets / name).read_bytes(),
            content_type={
                "index.html": "text/html",
                "app.js": "application/javascript",
                "style.css": "text/css",
            }[name],
        )

    async def api(request):
        body = await request.json()
        method = request.match_info["method"]
        if method == "enroll":
            return web.json_response({"secret": auth.enroll(body["code"], body["device"])})
        if method == "view":
            action = auth.action(body["request"])
            return web.json_response(
                {k: action[k] for k in ("id", "kind", "payload", "digest", "status", "expires")}
            )
        if method == "media":
            action = auth.action(body["request"])
            if action["kind"] != "input" or action["status"] != "pending" or action["expires"] <= time.time():
                raise ValueError("Media preview expired")
            rows = json.loads(action["payload"])["rows"]
            index = int(body["index"])
            if not 0 <= index < len(rows):
                raise ValueError("Invalid attachment")
            message = json.loads(rows[index]["body"])["message"]
            sid = "confirmation-" + action["id"]
            if message.get("voice"):
                path = await runtime.download_voice(message, sid)
                mime = message["voice"].get("mime_type", "audio/ogg")
                if mime not in {"audio/ogg", "audio/mp4", "audio/mpeg"}:
                    mime = "audio/ogg"
            else:
                path = await runtime.download_image(message, sid)
                mime = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                }.get(Path(path or "").suffix, "application/octet-stream")
            if not path:
                raise ValueError("No media in this message")
            return web.Response(body=Path(path).read_bytes(), content_type=mime)
        if method == "proof":
            return web.json_response(
                auth.proof(body["request"], body["device"], decision=body.get("decision", "approve"))
            )
        if method == "confirm":
            return web.json_response({"status": auth.confirm(body["proof"], body["signature"])})
        raise web.HTTPNotFound()

    app.router.add_get(prefix + "/", asset)
    app.router.add_get(prefix + "/{asset:index.html|app.js|style.css}", asset)
    app.router.add_post(prefix + "/api/{method}", api)
    return app

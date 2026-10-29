# Remote Vibecoding Notifier

## Purpose and security boundary

Telegram is a notification-only companion to the private Web Vibecoding
workspace. The owner explicitly retired agent access through Telegram because
an account compromise must not grant Codex access to VPS files, sudo or connected
services. Native execution and session management belong to the web interface
and Core. Do not restore executable Telegram intake, even behind a confirmation
screen, without a new explicit owner decision.

The production CLI imports notifier.run, which starts only update polling and
notification collection/delivery. It does not start the legacy interactive
runtime, inbox workers, media downloads, confirmation server, navigation,
question-answer submission or answer delivery. Existing legacy state and source
remain available for recovery/reference and are never replayed by this runtime.

Text, slash commands, photos, documents, voice, replies, edited messages and old
callback buttons cannot start, steer, stop, archive, rename or configure an agent,
register paths or answer native questions. Only the configured numeric owner in
that same private chat receives read-only replies. Unknown inputs explain this
boundary and link to the web workspace; unauthorized/group updates are ignored.
Incoming content is not copied into a durable inbox or downloaded.

A fail-closed Core client allows only GET /health, /sessions, /live and
/events?after=<numeric cursor>. It rejects every request body and all other paths
before transport, including GET attempts at mutation routes. No extra model,
prompt rewriting, native permission change or Core implementation import exists.

## Notifications and links

Send a boot notice, every new terminal outcome and questions requiring owner
input. Do not suppress notices based on a remembered Telegram selection. Native
answer/prompt/reasoning bodies and files remain in the private web chat; Telegram
receives metadata only. Every notice has a URL button to the exact captured
session using web_url/#<native session id>. There are no executable callback
buttons. Web access still requires the owner's VPN and browser trust.

Notices show outcome, session, host/path, selected model, effort and mode, work
duration and number of original/steering inputs in that run. Auto means Core did
not report an explicit session model; never invent the resolved active model.
Duration runs from the first retained user event after the previous terminal
event to this terminal event. Steering does not reset it. Missing evidence is
unavailable rather than session age. A run spanning activation may include time
and input from before activation, while aggregate counters include only events
observed after activation.

At first activation, scan retained events to establish current work intervals but
never notify historical outcomes. Persist event capture, aggregate counters and
cursor in one SQLite transaction; re-reading an event cannot count it twice.
Accepted Telegram message IDs are durable, so known successful delivery is not
repeated after restart. A failed send stays queued. Telegram provides no send
idempotency key, so an acknowledgement lost after acceptance can still duplicate
a notice; this never creates an agent input.

Each cycle drains at most ten Core event pages (100 events per v1 page),
keeping initial retained-history catch-up finite without delaying new outcomes
one page per poll. The three-second collection interval serves the owner's need for
prompt notifications without another service. At most ten queued notices are
sent per cycle, using the existing shared chat pacer (1.05 seconds between
writes) to bound Telegram traffic. Local metadata notices expire after 604800
seconds (seven days); small cursors/counters remain. No prompt/answer content
enters this notice ledger. Boot identity remains per process.

## Read-only activity

/start and unsupported owner messages explain the notification-only boundary.
/status and /stats show host, active/waiting/session counts, observed input and
outcome totals, accumulated completed work duration and up to eight recent
sessions with path, model, reasoning, mode, status and elapsed active time.
The eight-row bound keeps the response inside Telegram's message limit; exact
session work remains in the web UI. These commands never invoke inference.
Do not claim token usage, billed cost, universal historical totals or an ETA.
Operational boot timestamps use Europe/Warsaw with the applicable CET/CEST label;
relative work durations do not depend on a time zone.

## State and delivery

The notifier owns ~/.local/state/remote-vibecoding-notifier/bot.db and its own
process lock. It does not write Core's engine.db or legacy bot.db. Preserve legacy
shared state and credentials outside Git, without running the old interactive
poller. The notifier token is a mode-0600 file, separately configured and pinned
by its verified Telegram username. Never expose credentials or incoming content
in logs. A mismatched configured username prevents startup.

The shared Compose definition belongs to Core. Bot mounts are limited to its own
state directory, the read-only Core socket directory, configuration and notifier
token. A read-only socket bind alone does not restrict its protocol; the client
allowlist supplies that application boundary. There is no host home mount,
captured upload mount, native database mount or published confirmation port.
Updating only bot must preserve Core container/native session identity.

Readiness checks the current boot/PID and successful Telegram polling heartbeat
within 120 seconds. Polling uses a 25-second Telegram wait and 35-second request
deadline, permitting transient failures within that bound. Failed polling and
notification operations retry after three seconds and log only exception types.

## Recovery and independent versioning

The component owns its version, changelog, release commit/tag and package
metadata. Run make check and the Kernel release workflow. Shared activation and
rollback accept only images reporting notifications-only through --capabilities.
A failed first cutover stops the bot rather than restoring an interactive image;
later notification-only revisions retain normal rollback. Independent Core/web
updates and native execution remain available.

Legacy Core snapshots include the old shared bot.db. The new notifier ledger is
separate: preserve it with a consistent SQLite backup when backing up this
component. Losing only this ledger starts a fresh observation baseline without
executing anything or backfilling historical notifications. Core/native history
and the owner's existing backup retention remain unchanged.

Source map: notifier.py owns live Telegram behavior; client.py owns its read-only
API boundary; config.py owns private settings; cli.py owns entrypoint/readiness;
store.py owns SQLite support; Core owns shared Compose/deployment. Other UI,
book, confirmation and formatting modules support legacy recovery/tests and are
not imported by the production notifier entrypoint. Work personally; no subagents.

# Remote Vibecoding Notifier

Telegram receives completion/question notifications and read-only activity
statistics. All Codex requests and session controls belong in the private
[Web Vibecoding workspace](https://vibecoding.com), reached through the owner's
VPN. Telegram text, files, voice, slash commands and old buttons cannot invoke
or control an agent. Use /status or /stats for current activity.

Every notice links directly to its native web chat and shows host/path, selected
model/reasoning/mode, elapsed work and input count. Auto does not claim to identify
the engine's resolved model. Prompt bodies, answers and files remain in web chat.

Run make install and make check. Integration checks use the sibling Core fixture;
production code uses only its private API and has no Core implementation import.
The CLI starts the notification-only runtime. Legacy interactive modules and
state are preserved for recovery, but the old execution workflow is retired.

Private bot.toml selects the numeric owner, verified bot_username, web_url,
Core runtime_dir and the notifier's own data_dir. Store the notifier token in
~/.config/remote-vibecoding/notifier-token with mode 600. Verify getMe before
cutover; the owner must open the intended bot and press Start before Telegram
will accept notifications. Never put the token in commands, Git or logs.

The shared Compose deployment mounts only the notifier state, read-only API
socket directory, config and token, without a confirmation port. Run make
deploy-bot from the parent workspace after checks/commit. Activation and rollback
reject images without the notifications-only capability. A failed first cutover
stops Telegram instead of restoring an interactive bot; Core continues running.
See [Core operations](../vibecoding-core/docs/operations.md) for the shared owner.
Preserve the old token and shared bot state without starting the old poller.
Back up the new notifier SQLite ledger consistently; legacy Core snapshots cover
the previous shared bot.db. Losing notifier metadata creates a new observation
baseline; it cannot execute an input.

Run make release interactively, enter the exact version, then make release-push.
Versions, changelog and annotated tags are independent of Core/web. --capabilities
reports notifications-only without requiring credentials. See [BUSINESS.md](BUSINESS.md)
for the security boundary, statistics definitions, retention and recovery.

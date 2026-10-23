# Source provenance

The working Telegram transport, dialog and presentation code was extracted from
RoTorEx/vibecoding-core commit 55942781c632d786c3c904a99779b2c2b58d1433, originally
the combined codex-relay repository. Its complete earlier history remains in
the Core repository. This separate repository starts with an operational
foundation commit and then imports the frontend with the existing meaningful
interaction, persistence, media, restart and delivery checks.

Production imports now stay within telegram_vibecoding. Core interaction is
through the documented Unix-socket API. Integration tests use the sibling Core
source checkout, not a production package dependency.

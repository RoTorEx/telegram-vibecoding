# Telegram Vibecoding

## Purpose and actors

Aleksey uses this private Telegram interface to work with native host agents
through Vibecoding Core. Only the configured numeric owner in their private
chat may send input or use callbacks. No extra LLM or rewritten prompts.

## Interaction contract

Main Deck has a full-width primary Settings button first, then Location.
Every screen ends with Deck and Back in one row. Home is the default first
location. Numbered 1–10 controls page through locations and directory-scoped
sessions and archives. Selecting a location does not start an agent. New
session appears only within a location. Other location registers an existing
host directory without creating a session.

A session normally shows its title/status, original request and agent response
in one editable panel. Previous/Next browse complete retained exchanges and
long Unicode parts; Latest follows live output. Original Telegram messages
are preserved. Config selects the latest available Sol and up to two latest
Astra models, cycles supported reasoning in place and toggles native Plan mode.
Settings apply to the next native turn without stopping active work.

Details contains title, host, directory, location, creation/request/response/
completion times and free disk space. Rename and Close live here. Times use
Europe/Warsaw and their date-specific UTC offset. Navigation leaves work running;
Stop interrupts it; Close archives without deleting project files.

## Transport and state

Text and supported images pass unchanged to Core. New messages steer active
work. The 20 MB Telegram cloud download ceiling is enforced. Conversation parts
are at most 3200 UTF-16 units, leaving room for the header and notices below the
4096-unit API limit. Albums use a one-second quiet window and retain their first
captured target. Outgoing changes are throttled to at least one second, with
Telegram retry_after taking precedence.

The frontend owns bot.db: captured input, UI state, offsets and output refresh
requests. Input targets are captured before downloads/navigation. Button navigation and streaming edit the current panel. A new owner message
moves the panel below that input by sending the replacement first and retiring
the previous bot panel. Telegram edits cannot change message order. Preserve
all owner messages and stored conversation history. Track the latest input and
unfinished retirement durably, including across upgrades. A failed replacement
send preserves the old panel; failed cleanup never repeats the successful send.
Startup refreshes the saved view and repairs a panel stranded above newer input. Native questions and free-text
answers remain associated with their originating session. Errors retain
navigation exits. An unavailable panel can be replaced without replaying input.

## Deployment boundary

This is one of two containers in the Remote Vibecoding Compose project.
Production code talks only to the versioned Core API, never imports Core code.
Integration tests use the sibling Core checkout; runtime packaging does not.
Restarting/updating this container must not restart Core or native agent work.
The accepted bot is @GardenSandbox_bot, displayed as Telegram Vibecoding.
Voice and additional hosts are later stages. No subagents.

## Independent versioning

This component owns its semantic version, changelog, release commit and annotated
vMAJOR.MINOR.PATCH tag. The sibling version and deployment revision do not change
when this repository is released. API protocol compatibility is separate from
product versions. Follow the local Kernel release contract through make release
and make release-push. Source package version, built metadata, CLI and runtime
version reports must agree.

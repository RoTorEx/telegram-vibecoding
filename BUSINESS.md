# Telegram Vibecoding

## Purpose and actors

Aleksey uses this private Telegram interface to work with native host agents
through Vibecoding Core. Only the configured numeric owner in their private
chat may send input or use callbacks. No extra LLM or rewritten prompts.

## Interaction contract

Main Deck has a full-width Settings button first, then Location. Use Telegram's
default button styling without a primary color accent.
Every screen ends with Back on the left and Deck on the right in one row. Home is the default first
location. Numbered 1–10 controls page through locations and directory-scoped
sessions. Selecting a location does not start an agent. New session appears only
within a location. Locations are existing registered directories; do not expose
a manual Other location input action in this menu. Config belongs to an open
session and its nested views, never the location/session lists or global Settings.

A session normally shows its title/status, original request and agent response
in one editable panel. Previous/Next browse complete retained exchanges and
long Unicode parts; Latest follows live output. Original Telegram messages
are preserved. Config selects the latest available Sol and up to two latest
Astra models, cycles supported reasoning in place and toggles native Plan mode.
Settings apply to the next native turn without stopping active work.

Details contains title, host, directory, location, creation/request/response/
completion times and free disk space. Rename and Close live here. Times use
Europe/Warsaw and their date-specific UTC offset. Navigation leaves work running;
Stop interrupts it; Close ends the session without deleting project files.
The bot has no archive browser or reopen action; closed history remains stored.

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
Voice recordings are downloaded privately and queued to Core for local speech
recognition. Display the exact transcript as user input. One recording is limited
to five minutes and 20 MB; stable downloads and captured targets survive retries.
Video is out of scope.
Additional hosts remain deferred. No subagents.

## Independent versioning

This component owns its semantic version, changelog, release commit and annotated
vMAJOR.MINOR.PATCH tag. The sibling version and deployment revision do not change
when this repository is released. API protocol compatibility is separate from
product versions. Follow the local Kernel release contract through make release
and make release-push. Source package version, built metadata, CLI and runtime
version reports must agree.

## Active work display

The one-panel positioning rule applies to every owner message and command,
including plain menu input, attachments, input steps and Stop without a session.
Unknown bot commands stay in the interface instead of reaching an agent; absolute
directory input remains valid. Accepted agent input refreshes the panel promptly.

While a turn is active, animate a compact working indicator with elapsed time
and the configured reasoning effort. Never invent remaining time. Show only
public native summaries and code-free progress prose, separated chronologically
above the finished answer. Hide command/tool output, diffs and code blocks from
progress. Do not display raw reasoning. Final answers and original user prompts
remain intact. Completed summaries stay browsable in the paginated history.

Session lists show at most ten entries per page. When multiple pages exist,
left/right arrows share one row and clamp at the first/last page. A completed
answer shows its age as s, m, h or d; working/transcribing sessions show an
hourglass and questions awaiting the owner show a question marker. Ages refresh
while the list is open; metadata edits do not reset the response timestamp.

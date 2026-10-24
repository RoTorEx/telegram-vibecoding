# Changelog

## [Unreleased]

## [0.1.10] - 2026-10-24

- Fix incoming button/reply serialization of SDK link-preview defaults that could block all commands behind one update.
- Recover expired callback acknowledgements and detect stalled polling in health checks.

## [0.1.9] - 2026-10-24

- Add Main Deck unread-result counts and a paginated Journal with durable explicit-view acknowledgements.
- Notify the owner on bot restart while preserving the selected session and single-panel navigation.

## [0.1.8] - 2026-10-24

- Hide untouched empty session drafts from location lists while preserving their records and history.
- Use 👽 for Main Deck and Deck navigation, and show location names in bold with plain paths in parentheses on one line.

## [0.1.7] - 2026-10-24

- Render agent Markdown as safe Telegram formatting with readable table rows and balanced formatting across history pages; keep original messages intact.

## [0.1.6] - 2026-10-23

- Keep Stop available during voice preprocessing and refresh the transcript as soon as it is stored.

## [0.1.5] - 2026-10-23

- Accept Telegram voice recordings, preserve their captured session and show local transcripts in user history; video remains unsupported.

## [0.1.4] - 2026-10-23

- Show compact last-response ages and active-work markers in ten-session pages,
  with paired left/right controls and periodic visible-list refreshes.

- Remove manual location entry and archive browsing/reopening from the interface.
  Keep Config inside an open session and use Back-left/Deck-right footers on
  every screen. Recover an already-open retired archive view safely.

- Use Telegram's default Settings button styling while retaining its full-width
  first row.

## [0.1.3] - 2026-10-23

- Apply panel positioning to every message/command, including empty Stop and
  unknown commands, and refresh promptly after agent input is accepted.
- Animate active work with elapsed time and reasoning effort. Show public
  summaries as separated history blocks while hiding live code and tool output;
  preserve final answers and original user input.

## [0.1.2] - 2026-10-23

- Keep the active panel below new owner messages: Start/Menu, text and media
  relocate it to the chat tail while buttons and streaming edit it in place.
- Repair stranded panels from the durable inbox at startup. Retire old bot
  panels only after replacement succeeds, retry cleanup without duplicate sends
  and recover expired controls directly into Main Deck.

## [0.1.1] - 2026-10-23

- Add independent Kernel-compliant interactive release and atomic tag publishing,
  with one canonical package version and matching CLI/build metadata.
- Show the independently running Telegram and Core versions in Settings.

- Extract the working Telegram interface into its own private repository and
  runtime package, preserving UI, session routing and durable state.
- Add a separate image/container and per-boot readiness for one Remote Vibecoding
  Compose workspace with independently managed Core.

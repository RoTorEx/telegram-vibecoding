# Changelog

## [Unreleased]

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

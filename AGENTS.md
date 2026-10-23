# AGENTS.md

Keep this file a short context router. Put product truth in `BUSINESS.md` and
focused `business/*` modules instead of expanding this file.

## Kernel routing

<!-- VIBE:KERNEL_ROUTING_START -->

This project uses committed local copies of the Vibecoding Kernel.

- Always read `.vibe/kernel/OPERATING.md` and choose its maintenance, operation,
  or audit mode before normal project work.
- For version, tag, publish, or release work, also read
  `.vibe/kernel/RELEASE.md`.
- For user corrections, instruction conflicts, reusable agent-workflow lessons,
  kernel proposals, or a newly pulled kernel version, also read
  `.vibe/kernel/EVOLUTION.md`.
- For product behavior or domain logic, read `BUSINESS.md` and only the relevant
  module from `business/*`.
- Do not edit `.vibe/kernel/*` manually or read the parent kernel during normal
  work. Refresh the local copy with `make vibe-pull`.
- When a reusable workflow improvement belongs in the parent, run
  `make vibe-propose`; it appends a reviewable proposal without changing rules.

<!-- VIBE:KERNEL_ROUTING_END -->

## Local rules

- Preserve durable user explanations and corrections in the appropriate local
  source of truth during the same task.
- Use `.vibe/kernel/EVOLUTION.md` for reusable workflow feedback; never block a
  local fix while waiting for a parent-kernel decision.
- Add project-specific routing here only when it prevents repeated mistakes or
  unnecessary context loading.

## Project routing

- Work personally, without subagents.
- Read BUSINESS.md before changing conversation or navigation behavior.
- Read docs/architecture.md for persistence, transport, and recovery.
- Read docs/operations.md before installation, deployment, backup, or rollback.
- Run make check; exercise meaningful lifecycle and routing behavior.
- Bot deployment must never restart the engine. Agent turns have full host access
  by explicit owner choice; do not introduce prompt rewriting or execution gates.
- Keep credentials, Codex history, and runtime databases outside Git and logs.
- Write code and project artifacts in English.

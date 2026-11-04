# Versioned Identity browser contract fixture

`session.d.ts` and `accounts/index.ts` describe the published Identity Accounts v1 browser handoff. They are used only by `tests/lanes/L07/tsconfig.json` before L01 is merged. They contain types only, no runtime behavior or fabricated authority. Production feature code imports the canonical `@/features/identity/session` implementation supplied by L01. They are never an alternate browser session provider in the application.

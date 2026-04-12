# Backend Architecture Patterns

## Use This File

Read this file when the task is not just a small endpoint edit and you need guidance on where logic should live or how to avoid backend regressions.

## Request Boundaries

- Keep parsing and validation at the boundary.
- Keep business rules in services or use-case modules.
- Keep persistence concerns in repositories, ORM helpers, or clearly named data-access modules.
- Keep transport-specific formatting close to the transport layer.

## Data Integrity

- Use transactions for multi-write invariants.
- Prefer database constraints for rules that must never be violated.
- Treat application checks as helpful but insufficient when concurrent writes are possible.

## Migrations

- Prefer additive migrations first: new columns, nullable fields, dual reads, then cleanup later.
- Avoid combining irreversible destructive schema changes with application changes in a single risky deploy.
- If a backfill is needed, decide whether it runs inline, as a one-off script, or as a background task.

## Async Work

- Assume jobs and webhooks may be retried.
- Keep handlers idempotent or explicitly deduplicated.
- Persist enough state to recover from partial completion.

## Observability

- Log identifiers and outcomes, not secrets.
- Emit metrics around failures, retries, and latency where the codebase already has instrumentation.
- Make operationally important branches visible in tests and logs.

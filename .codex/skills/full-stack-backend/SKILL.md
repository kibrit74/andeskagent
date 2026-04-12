---
name: full-stack-backend
description: Build and modify backend systems for full-stack applications, including API routes, service layers, database schema changes, authentication, background jobs, integrations, and production-safe testing. Use when Codex needs to implement or review server-side work that touches application logic, persistence, contracts with the frontend, or backend delivery checklists.
---

# Full Stack Backend

## Overview

Implement backend changes with a delivery mindset: trace the request path, keep contracts explicit, preserve data correctness, and verify the behavior from storage to API surface.

## Quick Start

1. Inspect the existing backend structure before changing code. Identify the entrypoints, request handlers, service layer, persistence layer, validation boundary, and test setup.
2. Trace the user-visible behavior. Confirm which frontend or external client contract depends on the backend change.
3. Choose the narrowest safe change that fits the existing architecture. Extend current patterns before introducing new abstractions.
4. Update the code path end to end. Keep types, schema, validation, authorization, and serialization aligned.
5. Verify behavior with the most direct checks available: targeted tests first, then broader suite coverage if needed.

## Workflow

### 1. Build Context

- Find the request entrypoint first: route, controller, RPC procedure, webhook handler, queue consumer, or scheduled job.
- Locate the domain logic owner: service, use-case module, repository, model hook, or transaction helper.
- Identify the source of truth for schema and validation: ORM schema, SQL migration, zod/joi/schema object, OpenAPI spec, or framework-specific validators.
- Check how auth is enforced and propagated. Do not assume middleware and handler checks are equivalent.
- Read nearby tests before editing. They reveal invariants faster than broad code search alone.

### 2. Design The Change

- Keep contract changes explicit. If request or response shape changes, update all validators, types, docs, and tests in the same pass.
- Prefer additive database migrations unless a destructive migration is clearly safe.
- Preserve idempotency for webhooks, retries, and background jobs.
- Use transactions when multiple writes must succeed or fail together.
- Avoid leaking persistence concerns into the API surface unless the codebase already follows that pattern.

### 3. Implement Safely

- Validate untrusted input at the boundary, not halfway through the flow.
- Normalize errors into the project's existing error model.
- Enforce authorization close to sensitive actions, not only at routing level.
- If caching exists, update invalidation or revalidation paths in the same change.
- If a feature flag or rollout guard exists nearby, follow that mechanism instead of bypassing it.

### 4. Verify

- Run the smallest tests that prove the changed path works.
- Add or update tests for regressions at the right layer: unit for branching logic, integration for persistence/HTTP behavior, end-to-end only when contract wiring is the real risk.
- Check failure paths, especially validation errors, permission failures, duplicate writes, and missing-record behavior.
- If migrations are involved, verify both new writes and reads of pre-existing rows.

## Backend Change Patterns

### API Endpoints

- Update request validation, handler logic, service calls, response serialization, and contract tests together.
- Keep transport concerns thin. Move nontrivial business logic out of controllers/routes unless the project intentionally inlines it.

### Database Changes

- Read `references/architecture-patterns.md` before large schema or transaction changes.
- Prefer forward-only migrations.
- Backfill deliberately. If old and new code may coexist during rollout, maintain compatibility.

### Auth And Permissions

- Make actor, scope, and resource ownership checks visible in code review.
- Distinguish authentication, authorization, and tenant scoping. These fail in different ways and need separate tests.

### Async Jobs And Webhooks

- Treat retries as normal behavior.
- Add deduplication, locking, or idempotency keys where duplicate execution would be harmful.
- Log enough context to debug job failures without exposing secrets.

### Third-Party Integrations

- Isolate vendor-specific code behind a local adapter when the integration is nontrivial.
- Fail predictably on timeouts, partial responses, and upstream schema drift.

## Reference Files

- For a practical change checklist, read `references/delivery-checklist.md`.
- For patterns around boundaries, data integrity, and migrations, read `references/architecture-patterns.md`.

## Output Expectations

- State the behavior change in backend terms and in user-visible terms.
- Mention contract or schema changes explicitly.
- Call out migration, rollout, or data backfill risk when relevant.
- If verification is incomplete, say exactly what was not run.

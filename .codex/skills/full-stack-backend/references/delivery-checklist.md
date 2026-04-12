# Backend Delivery Checklist

## Use This File

Read this file when the task includes endpoint changes, database writes, auth changes, integrations, or any backend change that could ship with hidden operational risk.

## Checklist

### Contracts

- Confirm the exact request and response shape.
- Update validation, types, serialization, and tests together.
- Check whether frontend consumers, mobile clients, webhooks, or external users depend on the old contract.

### Data

- Identify every table, document, cache key, or queue affected.
- Verify whether the change is additive, mutating, or destructive.
- For schema changes, define the compatibility window between old and new code.

### Auth

- List the actor making the request.
- Confirm authentication source.
- Confirm authorization rules and tenant/resource scoping.

### Failures

- Define the expected behavior for invalid input, missing records, duplicates, timeouts, and upstream failures.
- Verify error shape and status codes match existing conventions.

### Testing

- Prefer targeted tests for the changed execution path.
- Add regression coverage for the branch most likely to break again.
- If test coverage is skipped, say why and describe the remaining risk.

### Rollout

- Call out migrations, backfills, feature flags, and cache invalidation.
- Note whether the change is safe to deploy gradually or requires a coordinated release.

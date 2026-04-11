---
name: windows-support-workflows
description: Use when working on this repository's Windows technical support agent, especially for chained remediation flows such as diagnose -> act -> verify -> fallback. Prefer this skill for Python/Path issues, mail session recovery, app startup failures, and any request that should become a multi-step support workflow instead of a single command or a manual instruction dump.
---

# Windows Support Workflows

Use this skill when the request is not just "run one action", but "solve a support problem".

## Goal

Turn support intents into executable workflows with:
- a detection step
- one or more remediation steps
- a verification step
- fallback only after at least one concrete attempt

## Default Pattern

1. Identify whether the issue matches an existing deterministic workflow.
2. Prefer repository primitives over freeform scripting.
3. Return step-by-step results the UI can render as a workflow.
4. If the first fix fails, add a second bounded fallback step.
5. Only recommend ticket escalation after executable remediation is exhausted.

## Existing Building Blocks In This Repo

- Workflow engine: `core/workflows.py`
- Command execution planner: `adapters/script_adapter.py`
- Command route: `server/routes/command.py`
- UI workflow renderer: `mobile-cli/app.js`

## Use These Patterns

### Remediation workflows

- Python command broken:
  Detect working binary, prepare shim, write shims, update user PATH, instruct terminal restart.
- Mail session not ready:
  Open mail target, wait for window, focus it, collect screen state.
- App/window guidance:
  Open app, wait for window, focus window, optionally inspect screen.

### Verification rules

- A step is not complete just because it ran.
- Verify created files exist, windows are found, PATH contains the shim, or screen/window inventory confirms the expected state.
- If verification fails, the step should be marked failed and the workflow should stop or branch.

## Safety

- Keep destructive actions behind explicit approval.
- Do not add fake integrations or claim a workflow exists unless the repo can execute it.
- For unsupported support issues, add the nearest safe executable workflow instead of dumping manual instructions.

## Implementation Notes

- Prefer extending `adapters/script_adapter.py` for reusable workflow entrypoints.
- Keep workflow outputs structured with `summary`, `steps`, `step_count`, and status fields.
- When changing behavior, keep `mobile-cli` rendering aligned so the user sees readable step results.

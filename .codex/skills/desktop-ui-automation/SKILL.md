---
name: desktop-ui-automation
description: Use when implementing or updating this repository's desktop interaction flows: open application, wait for window, focus window, click, type, read screen, screenshot, or any chained UI automation on Windows. Trigger this for requests involving visible windows, button clicks, typing into apps, or screen-based verification.
---

# Desktop UI Automation

Use this skill for physical desktop interactions.

## Goal

Make UI tasks executable as stable chains instead of one-off hacks.

## Available Primitives In This Repo

- `open_application`
- `wait_for_window`
- `focus_window`
- `click_ui`
- `send_keys`
- `read_screen`
- `take_screenshot`

These are primarily wired in `adapters/script_adapter.py` and `adapters/desktop_adapter.py`.

## Preferred UI Chain

1. Open or locate the target app.
2. Wait for the expected window.
3. Focus the window.
4. Perform UI interaction:
   - click
   - type
   - press enter
5. Verify with window state or screen collection.

## Rules

- Do not jump straight to `send_keys` if the target window is not ready.
- Do not click blindly if a window/process target is known.
- If coordinates are used, keep them as a last resort and return them clearly in results.
- Always prefer "open -> wait -> focus -> interact -> verify".

## When To Use `unknown` / planner workflows

If the request includes more than one UI action, or needs verification, route it into workflow-style handling rather than a single direct action.

Examples:
- "Outlook'u ac ve ekrani oku"
- "Chrome'u ac, pencereyi bekle, sonra yaz"
- "Butona tikla, olmadiysa ekran goruntusu al"

## UI Output Contract

Return structured step output that the mobile UI can render:
- title
- status
- result or error

Avoid raw JSON dumps in user-facing responses when a readable step list can be returned.

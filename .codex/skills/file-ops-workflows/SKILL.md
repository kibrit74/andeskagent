---
name: file-ops-workflows
description: Use when implementing or adjusting chained file operations in this repository: search, create folder, create file, write text, copy, move, rename, delete, and fallback search across Desktop/Documents/Downloads. Trigger this when the user intent mentions files, folders, writing into files, or sequential file workflows.
---

# File Ops Workflows

Use this skill for file and folder behavior in the support agent.

## Goal

Convert natural language file requests into safe, explicit file workflows.

## Existing Primitives

- Search: `search_files`
- Copy: `copy_file_to_location`
- Create folder: `create_folder_in_location`
- Create text file: `create_text_file_in_directory`
- Find file in directory: `find_file_in_directory`
- Write text: `write_text_to_file`

Core file logic lives in `adapters/file_adapter.py`.

## Preferred Workflow Shapes

### Find and act

1. Search preferred location.
2. Fallback to Desktop/Documents/Downloads when appropriate.
3. Select the best match.
4. Perform the requested action.

### Ensure container then file

1. Ensure the folder exists.
2. Find the target file.
3. If missing, create it.
4. Write or copy content.

## Important Parsing Guardrails

- Do not treat full sentences as folder names or file names.
- If the request includes both a folder and a file action, prefer a chained workflow.
- Requests like "X klasorundeki Y dosyasina Z yaz" should never collapse into `create_folder`.

## Safety

- Respect allowed folders only.
- Keep delete/move/rename operations approval-gated once implemented.
- Return structured, human-readable results with file path, chosen location, and action outcome.

## Files To Check When Editing

- `adapters/file_adapter.py`
- `core/command_parser.py`
- `server/routes/command.py`
- `adapters/script_adapter.py`

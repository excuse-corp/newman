# Prompt Templates

This directory stores prompt source files used by the backend.

- `*_template.md` files are seed templates for stable memory initialization.
- These files are copied into `backend_data/memory/` only when the target memory file does not already exist.
- After initialization, runtime prompt assembly reads from `backend_data/memory/`, not from these template files.
- `error_feedback.md` is different: it is a runtime template that is rendered directly when a tool call fails.
- `mem_extract.md` is also different: it is the runtime prompt used to classify prior-session content into `USER.md` and `MEMORY.md`.

---
name: Python runtime for imported bots
description: Environment-specific guidance for running imported Python applications with dependencies.
---

Imported Python applications nested inside the shared workspace use the managed workspace Python environment. Install dependencies through the project package-management flow rather than system pip; the environment may create root-level `pyproject.toml`/`uv.lock` metadata and a shared `.pythonlibs` directory.

**Why:** The imported bot runs from a subdirectory, while Replit's managed Python environment is provisioned at the workspace level. The shared interpreter remains available after `cd` into the imported project.

**How to apply:** Keep the workflow command directory-aware (`cd <project> && python app.py`), use the managed installer for dependencies, and verify imports from that exact workflow command before debugging application code.
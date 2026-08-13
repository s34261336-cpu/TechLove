---
name: Python runtime setup
description: Python dependency installation behavior in the Replit workspace
---

For Python projects, the base Python module may be externally managed and reject package installation into the system interpreter. Use a full available Python tools module with pip (for example, Python 3.12) before installing project dependencies.

**Why:** The base module can expose Python but not a writable package environment, so dependency installation fails before the application can start.

**How to apply:** Check available Python modules first; if the base module is active, switch to a full tools module and keep the project requirement and run configuration aligned with that version.
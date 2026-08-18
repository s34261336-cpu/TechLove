---
name: Python runtime for imported bots
description: Environment-specific guidance for running imported Python applications with dependencies.
---

Imported Python applications may need the managed Python 3.11 runtime before dependency installation; the base Python executable can be externally managed and lack pip. Use the project package-management flow rather than system pip.

**Why:** The first package installation attempt failed because the base Python environment was immutable and had no pip; installing the managed runtime enabled the package manager to install dependencies into the project environment.

**How to apply:** For imported Python projects, check the available Python modules early and install a compatible managed runtime before installing `requirements.txt`; inspect Git status afterward because package setup may update project config files.
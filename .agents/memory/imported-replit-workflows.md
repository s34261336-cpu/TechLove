---
name: Imported Replit workflow manifests
description: GitHub imports can contain nested Replit artifact manifests that auto-register duplicate workflows.
---

When importing a repository that was previously created from a Replit workspace, inspect nested `.replit-artifact/artifact.toml` files before starting services; the platform may register one workflow per nested copy.

**Why:** A repository can include copied `artifacts/`, `techlove/`, and `new_project/` trees alongside the real app, causing duplicate API/Canvas workflows and unnecessary resource use.

**How to apply:** Keep the app's intended workflow running, stop unrelated auto-registered services, and only remove nested manifests when the user explicitly wants the imported repository cleaned up.
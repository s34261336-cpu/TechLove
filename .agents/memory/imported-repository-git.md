---
name: Imported repository Git state
description: Preserve the managed workspace .git directory when importing a repository into an existing Replit project.
---

When importing a GitHub repository into an existing Replit project, preserve the workspace-managed `.git` directory and synchronize the repository state through its configured remote instead of replacing `.git` directly.

**Why:** The managed Git directory can contain platform permissions and workflow metadata that make direct replacement fail or remove useful workspace state.

**How to apply:** Copy project files without `.git`, set the requested remote, fetch the target branch, and reset to that remote branch before starting the imported workflow.
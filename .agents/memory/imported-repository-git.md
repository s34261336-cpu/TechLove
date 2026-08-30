---
name: Imported repository Git state
description: Preserve the managed workspace .git directory when importing a repository into an existing Replit project.
---

When importing a GitHub repository into an existing Replit project, preserve the workspace-managed `.git` directory and synchronize the repository state through its configured remote instead of replacing `.git` directly. Keep runtime JSON data separate from code fast-forwards so bot activity is never overwritten during an update.

**Why:** The managed Git directory can contain platform permissions and workflow metadata that make direct replacement fail or remove useful workspace state.

**How to apply:** Copy project files without `.git`, set the requested remote, fetch the target branch, and reset to that remote branch before starting the imported workflow. During later fast-forwards, back up and restore local runtime data, and skip the update if non-data local edits are present.
# ORCA Automation Pipeline
## 22nd Century Programer Bot Edition ⚡

... (previous sections unchanged) ...

### ♻️ Crash-safe Recovery

This pipeline is designed to automatically resume after unexpected termination (power loss, crash, Ctrl+C):

- Persistent state under `folders/state/`:
  - `queue.json` — jobs waiting to run
  - `running.json` — jobs that were running (reconciled on restart)
  - `completed.json` — job history
- Atomic writes ensure consistency across crashes
- On startup, the pipeline will:
  1. Requeue all jobs from `queue.json`
  2. Inspect each `running` entry and its working directory:
     - If output indicates normal termination, files are archived and job is marked completed
     - Otherwise the job is requeued (with retry counter)
  3. Scan `folders/waiting/` for orphan `.inp` files and enqueue them
- Lock files: each running job creates a `.lock` in its working directory and removes it on completion
- Retry policy: configurable via `config.txt`

**Config**
```ini
[orca]
max_retries = 2  # number of retries for failed jobs before marking as failed
```

**Logs**
```
[RECOVER] Starting recovery...
[RECOVER] queued -> requeue ...
[RECOVER] running(ok) -> completed ...
[RECOVER] running(failed) -> requeue ...
[RECOVER] waiting -> enqueue ...
[RECOVER] Done
```

### 🔐 Environment Variables for Gmail

For secure operation, set these environment variables (fallback to config.txt if missing):
- `GMAIL_USER`
- `GMAIL_APP_PASSWORD` (spaces removed automatically)
- `GMAIL_RECIPIENT`


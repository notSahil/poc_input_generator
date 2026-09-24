# Infrastructure & Operations Architecture Decision Records (ADRs)

> Historical context explaining WHY Oracle Cloud VM, browser-based code-server, SQLite WAL job store, and multi-channel alerting were built this way.

---

### ADR 3: Environment Setup (Oracle Cloud & Browser-Based Development)
- **Decision:** No local installations on the company laptop. Everything runs remotely via `code-server` in the browser on Oracle Cloud Ubuntu.
- **Reason:** Bypasses company laptop software restrictions and security lockouts. Streamlit hot-reloading is used to instantly preview code saved in the browser IDE on port 8080 and 8501.

---

### ADR 28: Task Scheduler, SQLite WAL Job Queue & Multi-Channel Alerting (`core/scheduler.py`, `core/job_store.py`, `core/notifier.py`, `ui/task_scheduler.py`)
- **Decision:** Build a zero-dependency, thread-safe persistent job store using SQLite with WAL mode (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`) in `data/jobs.db` instead of external queues like Huey or Celery. Enforce atomic concurrency locks (`job_locks`) on `(report_name, profile, target_object)`. Use `zoneinfo.ZoneInfo("Europe/London")` for strict UK timezone calculations supporting both recurring intervals (Hourly, Daily, Weekly, Monthly) and specific one-off datetimes with auto-deactivation. Provide an in-app notification center scoped to active environment profiles (`sandbox`, `partial`, `prod`), HTML transactional emails with execution KPI cards, and Slack/Teams webhooks with defensive error boundaries and token masking.
- **Reason:** Eliminates lost in-flight upload progress during `systemd` restarts on the Oracle Ubuntu VM, prevents overlapping concurrent uploads, removes the need for operators to babysit long batch uploads, and automates reconciliation on exact schedules with 100% backward compatibility for all existing report engines and zero additional daemon dependencies.

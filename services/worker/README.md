# worker

Celery worker + beat for NextStep.ai. It has no business logic of its own:
ingestion lives in the API package (`services/api/app/services/ingestion`),
and this service only wires it to Celery.

Run everything from the **repository root**:

```bash
source services/api/venv/Scripts/activate   # Windows Git Bash; .../venv/bin/activate elsewhere
pip install -r services/worker/requirements.txt   # installs services/api in editable mode

celery -A services.worker.celery_app worker --loglevel=info --pool=solo   # --pool=solo on Windows
celery -A services.worker.celery_app beat   --loglevel=info
```

| Module             | Purpose                                                              |
| ------------------ | -------------------------------------------------------------------- |
| `celery_app.py`    | Celery app; Redis (`REDIS_URL`) is both broker and result backend    |
| `tasks.py`         | `ingest_all_active_sources` — sweeps every active `job_sources` row  |
| `beat_schedule.py` | Runs that task every `INGEST_INTERVAL_MINUTES` (default 20)          |

Trigger a sweep by hand:

```bash
celery -A services.worker.celery_app call worker.ingest_all_active_sources
```

Checks:

```bash
cd services/worker && ruff check . && ruff format --check . && mypy . && pytest
```

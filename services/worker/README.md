# worker

Celery worker + beat for NextStep.ai. It has no business logic of its own:
ingestion lives in the API package (`services/api/app/services/ingestion`),
and this service only wires it to Celery.

Run everything from the **repository root**. Celery resolves
`-A services.worker.celery_app` against the current directory, so running it
from `services/api` fails with `ModuleNotFoundError: No module named 'services'`.

```powershell
# Windows PowerShell, from the repository root
.\services\api\venv\Scripts\Activate.ps1
pip install -r services\worker\requirements.txt    # installs services/api in editable mode

celery -A services.worker.celery_app worker --loglevel=info
celery -A services.worker.celery_app beat   --loglevel=info
```

```bash
# macOS / Linux / Git Bash, from the repository root
source services/api/venv/Scripts/activate   # or venv/bin/activate outside Windows
pip install -r services/worker/requirements.txt

celery -A services.worker.celery_app worker --loglevel=info
celery -A services.worker.celery_app beat   --loglevel=info
```

The worker pool defaults to `solo` on Windows (where Celery's prefork pool
cannot work: it needs `fork()`) and `prefork` everywhere else, so the same
command works on both. Override with `--pool=` if you need to.

| Module             | Purpose                                                              |
| ------------------ | -------------------------------------------------------------------- |
| `celery_app.py`    | Celery app; Redis (`REDIS_URL`) is both broker and result backend    |
| `tasks.py`         | `ingest_all_active_sources` — sweeps every active `job_sources` row  |
| `beat_schedule.py` | Runs that task every `INGEST_INTERVAL_MINUTES` (default 20)          |

Trigger a sweep by hand (also from the repository root):

```bash
celery -A services.worker.celery_app call worker.ingest_all_active_sources
```

Checks:

```bash
cd services/worker && ruff check . && ruff format --check . && mypy . && pytest
```

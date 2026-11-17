# Night Night

Night Night is a Duke EGR 101L design project: a chest-worn band that records a child's breathing movement overnight, for children aged 10–15 with neuromuscular disorders. This repository is the **software side**: a clinician-facing dashboard that reads the recordings and shows breathing rate and relative breathing depth across nights.

**Prototype. Synthetic and bench-test data only.** Nothing here is approved for patient data. Patients are identified only by study codes such as `NN-001`.

## What it does

- **Login** with email and password, or Google (Supabase Auth). Every page needs a session.
- **Patient list and overview:** each patient's nights with summary numbers and a trend of breathing rate.
- **Night view:** per-minute breathing rate and relative depth, with poor-quality minutes shaded. Below it, the raw signal with zoom, and the battery level at the end of the recording.
- **Compare nights:** overlay two or three nights, aligned by time since start or by clock time.
- **Clinician notes:** mark a moment or a stretch on the charts, with a category and a note.
- **Print report:** a one-page summary of a night.
- **Upload:**
  - check recordings from the microSD card in the browser, with nothing leaving the computer;
  - or save one to the server, where it is validated, stored and analysed.

## How it fits together

```
microSD file (.csv)
      │
      ├── checked in the browser ──► web/src/lib/processing (TypeScript copy of the algorithm)
      │
      └── saved to the server
              ▼
Browser ──► web/  Next.js on Vercel ──────────► Supabase Auth (login)
              │   checks the session
              │
              ├── static mode ──► web/data/*.json (bundled synthetic nights)
              │
              └── API mode ─────► api/  FastAPI ──► Supabase Postgres (metadata, per-minute metrics)
                  X-API-Key            │
                                       ├──► file store (raw files, compact signal files)
                                       └──► tools/processing (the breathing algorithm)
```

- The browser only ever talks to Next.js. Next.js checks the login session, then either reads bundled files or calls the API with a shared secret.
- The breathing algorithm is written once in Python (`tools/processing/`). The API imports it. The TypeScript copy for in-browser uploads is checked against it by a test.

| Folder | What it holds |
|---|---|
| `web/` | The dashboard: Next.js (App Router), TypeScript, Tailwind CSS, uPlot charts |
| `api/` | The backend: FastAPI, SQLAlchemy, Alembic migrations, upload and processing |
| `tools/` | Python scripts: synthetic data generator, the breathing algorithm, validation and the filter study |
| `sample_data/` | Ground truth for the synthetic nights (the large CSV files are generated, not committed) |
| `night_night_logger/` | The device firmware (owned by the hardware teammates) |
| `docs/` | Format descriptions, the filtering write-up, validation results, deployment steps, progress log |

## Run it locally

You need Node 26 (the version used here), Python 3.11 or newer, and a free Supabase project. Docker is not needed.

### 1. The dashboard

```powershell
cd web
npm install
# Create web/.env.local with the two values from Supabase (Project Settings → API Keys):
#   NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
#   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
npm run dev            # http://localhost:3000
```

This is enough to see every page with the bundled synthetic nights.

### 2. The API (optional)

```powershell
cd api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
# Create api/.env with DATABASE_URL (see .env.example; never commit it)
alembic upgrade head   # creates the tables
python seed.py         # loads the synthetic nights
uvicorn app.main:app --reload     # http://localhost:8000/docs
```

Then add `DATA_SOURCE=api` and `API_URL=http://localhost:8000` to `web/.env.local` and restart `npm run dev`.

### 3. The Python tools

```powershell
cd tools
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
python generate_sample_set.py     # the synthetic nights (about 670 MB, several minutes)
python validate.py                # accuracy against ground truth -> docs/VALIDATION.md
python filter_study.py            # filter figures -> docs/figures/filtering/
```

### Checks

| Where | Command | Expected |
|---|---|---|
| `web/` | `npm run lint && npx tsc --noEmit && npm test && npm run build` | 31 tests pass |
| `api/` | `ruff format --check . && ruff check . && pytest` | 37 tests pass |
| `tools/` | `ruff format --check . && ruff check . && pytest` | 42 tests pass |

## How breathing is measured

1. **Clean:** reject readings that are stuck, out of range, or sudden spikes. Bridge gaps of 2 s or less.
2. **Filter:** keep 0.1–1 Hz (6–60 breaths/min), running the filter forward and backward so breaths are not shifted in time.
3. **Find breaths:** peaks and troughs at least 1.0 s apart that stand out from the noise by 15% of a typical breath.
4. **Report:** breaths per minute, depth relative to the recording's typical breath, pauses longer than 10 s, and a quality label for each minute.

Results on 12 synthetic nights with known truth:

| Profile | Minutes within 5% of the true rate |
|---|---|
| Stable | 99.0% |
| Declining | 94.7% |
| Noisy | 99.2% |

The reasoning behind every setting, and what each one costs, is in [`docs/FILTERING.md`](docs/FILTERING.md). Full results are in [`docs/VALIDATION.md`](docs/VALIDATION.md).

## Known limits

- **Depth is relative, not a volume.** Turning it into litres needs calibration against a spirometer.
- **Breathing faster than about 50 breaths/min is under-reported**, and about one in six breaths shallower than 35% of normal is missed. Movement can be counted as extra breaths in minutes labelled poor. See `docs/FILTERING.md`.
- **One chest band cannot see a blocked airway**, because the chest keeps moving.
- **Validation is against our own synthetic model** and one short real recording. Comparison with hand counts and a clinical reference belt is still to come.
- **Deployed uploads are limited to small files**, and uploaded files do not survive a restart on a free host. See `docs/DEPLOY.md`.
- **No alerts, no user roles, no email verification.**

## More documentation

- [`docs/DEVICE_FORMAT.md`](docs/DEVICE_FORMAT.md): the file the device writes to the microSD card.
- [`docs/FILTERING.md`](docs/FILTERING.md): filter and detection settings, with measurements.
- [`docs/VALIDATION.md`](docs/VALIDATION.md): accuracy against synthetic ground truth.
- [`docs/DEPLOY.md`](docs/DEPLOY.md): putting it online.
- [`docs/HANDOFF.md`](docs/HANDOFF.md): status, decisions and gotchas for whoever picks this up.
- [`docs/PROGRESS.md`](docs/PROGRESS.md): dated log of every step.

## Team

Night Night, Duke EGR 101L.

# Deploying Night Night

There are two ways to put the dashboard online. Start with the first.

| | A. Dashboard only | B. Dashboard + API |
|---|---|---|
| What runs | Next.js on Vercel | Next.js on Vercel, FastAPI on a container host, Supabase Postgres |
| Data shown | The synthetic nights bundled in `web/data/` | The same nights from the database, plus recordings uploaded to the server |
| In-browser upload check | Yes | Yes |
| Save uploads to the server | No | Yes, for small files (see limits) |
| Effort | About 15 minutes | About an hour |

Both use the same Supabase project for login. **Synthetic or bench-test data only**: none of this is approved for patient data.

## A. Dashboard only (Vercel)

1. In Vercel, import the GitHub repository and set **Root Directory** to `web`.
2. Add two environment variables:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
3. Deploy. Note the address, for example `https://night-night.vercel.app`.
4. In Supabase, open **Authentication → URL Configuration**:
   - set **Site URL** to the Vercel address;
   - add `https://<your-app>.vercel.app/**` to **Redirect URLs**.
5. In Google Cloud Console, add the Vercel address to the OAuth client's **Authorized JavaScript origins**.
6. Check it:
   - logged out, every page sends you to `/login`;
   - logged in, the patient list, a night view and the waveform all load.

Supabase pauses a free project after about a week without activity. Open the Supabase dashboard the day before a demo and restore it if needed.

## B. Add the API

### 1. Choose a shared secret

The Next.js server proves who it is to the API with a secret. Make one:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

You will paste the same value into the API host and into Vercel. Do not commit it.

### 2. Deploy the API container

The steps below use Render, but any host that builds a Dockerfile works.

1. Create a **Web Service** from the GitHub repository.
2. Set these build settings:
   - **Runtime:** Docker
   - **Dockerfile path:** `api/Dockerfile`
   - **Docker build context:** `.` (the repository root, because the API also needs `tools/` and `web/data/`)
3. Add environment variables:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | The Supabase **Session pooler** string, starting `postgresql+psycopg://` |
   | `API_SHARED_SECRET` | The secret from step 1 |
   | `CORS_ORIGINS` | Your Vercel address |

4. Set the **health check path** to `/health`.
5. Deploy, then open `https://<your-api>/health`. It should answer `{"status":"ok",...}`.
6. Open `https://<your-api>/patients`. It should answer `401`, because no secret was sent.

On each start the container runs `alembic upgrade head`, restores the sample signal files, and then starts the server.

### 3. Point Vercel at the API

Add three environment variables in Vercel, then redeploy:

| Name | Value |
|---|---|
| `DATA_SOURCE` | `api` |
| `API_URL` | `https://<your-api>` |
| `API_SHARED_SECRET` | The secret from step 1 |

None of these may have a `NEXT_PUBLIC_` prefix. That prefix would send the value to every visitor's browser.

To go back to the bundled files, remove `DATA_SOURCE` and redeploy.

### 4. Check it

- The patient list and a night view load as before.
- The upload page shows a **Save a recording to the server** box.
- Upload a short trial file. It should move from "Saved" to "Processed" and then open as a night.

## Limits of the deployed version

- **Upload size.** Vercel rejects request bodies over about 4.5 MB. A three-minute trial is about 0.2 MB and works. A full night is about 60 MB and does not. Running both parts on your own computer has no such limit.
- **Uploaded files do not survive a restart on a free host.** The file store is a folder on the container's disk, and free hosts wipe that disk on restart. The database rows remain, but the signal chart for an uploaded recording will be empty until the file is uploaded again. The sample nights are restored automatically. The fix is a Supabase Storage bucket behind the `FileStore` interface in `api/app/storage.py`.
- **A free API host sleeps when idle.** The first request after a quiet period can take up to a minute.
- **Processing runs inside the web server.** A full night takes a few seconds. That is fine for a demo, but a real service would use a job queue.
- **The Dockerfile has not been built on the development computer** (Docker is not installed there). Expect to fix small things on the first build.

## Running everything locally

```powershell
# Terminal 1: the API
cd api
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload          # http://localhost:8000/docs

# Terminal 2: the dashboard
cd web
npm run dev                            # http://localhost:3000
```

For the dashboard to use the API, `web/.env.local` needs `DATA_SOURCE=api` and `API_URL=http://localhost:8000`.

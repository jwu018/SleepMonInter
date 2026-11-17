# Image for the Night Night API.
#
# Build from the REPOSITORY ROOT, not from api/, because the API also needs tools/ (the
# shared breathing algorithm) and web/data/ (the synthetic sample set it seeds from):
#
#     docker build -f api/Dockerfile -t night-night-api .
#     docker run --env-file api/.env -p 8000:8000 night-night-api
#
# Secrets (DATABASE_URL, API_SHARED_SECRET) are passed in as environment variables when the
# container runs. They are never copied into the image: .dockerignore excludes every .env.

FROM python:3.14-slim

# Print logs straight away, and do not write .pyc files into the image.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

# Install packages first, in their own layer. Docker reuses this layer on later builds
# unless requirements.txt changes, so code edits do not trigger a full reinstall.
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# Only what the API imports: the reader, the waveform packer and the algorithm.
COPY tools/device_csv.py tools/build_static_data.py tools/
COPY tools/processing tools/processing
COPY web/data web/data
COPY api api

# Run as an ordinary user, not root.
RUN useradd --create-home app && mkdir -p api/file_store && chown -R app /srv/api/file_store
USER app
WORKDIR /srv/api

EXPOSE 8000

# On start: bring the database schema up to date, restore the sample signal files (a free
# host wipes the disk on every restart), then serve. Hosts set $PORT; default 8000.
CMD ["sh", "-c", "alembic upgrade head && python seed.py --files-only && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

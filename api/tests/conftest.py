"""Shared test setup: a throwaway database and file store, so tests never touch Supabase.

The tests run against SQLite in memory. The models use only features both SQLite and
Postgres understand, so the same queries are exercised without a network or a password.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db, get_session_factory
from app.main import app
from app.models import Device, MinuteMetric, Patient, Recording
from app.storage import LocalFileStore, get_store

RECORDING = "NN-001_2026-09-14"
SAMPLE_RATE_HZ = 12.5
N_SAMPLES = 7500  # 10 minutes
MISSING = -32768
GAP = slice(2000, 2500)  # samples the "device" lost


def breathing_i16() -> np.ndarray:
    """A sine wave at 15 breaths/min in int16 steps, with one data gap."""
    t = np.arange(N_SAMPLES) / SAMPLE_RATE_HZ
    packed = np.rint(300 * np.sin(2 * np.pi * 0.25 * t)).astype("<i2")
    packed[GAP] = MISSING
    return packed


@pytest.fixture
def engine() -> Engine:
    # StaticPool: every connection is the SAME in-memory database (by default each new
    # SQLite connection would get its own empty one).
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def store(tmp_path: Path) -> LocalFileStore:
    return LocalFileStore(tmp_path)


@pytest.fixture
def seeded(db: Session, store: LocalFileStore) -> Session:
    """Two patients: NN-001 with two nights (one with a stored signal), NN-002 with none."""
    p1, p2 = Patient(study_code="NN-001"), Patient(study_code="NN-002")
    device = Device(device_code="NN-DEV-01")
    db.add_all([p1, p2, device])
    db.flush()
    start = datetime(2026, 9, 14, 2, 22, tzinfo=UTC)
    first = Recording(
        code=RECORDING, patient_id=p1.id, device_id=device.id, start_utc=start,
        end_utc=start + timedelta(minutes=4), sample_period_ms=40, status="processed",
        battery_start_mv=4130, battery_end_mv=3736, gap_count=1,
        waveform_path=f"waveforms/{RECORDING}.i16",
    )  # fmt: skip
    second = Recording(
        code="NN-001_2026-09-21", patient_id=p1.id, device_id=device.id,
        start_utc=start + timedelta(days=7), end_utc=start + timedelta(days=7, minutes=2),
        sample_period_ms=40, status="processed", gap_count=0,
    )  # fmt: skip
    db.add_all([first, second])
    db.flush()
    minutes = [
        (18.0, 1.0, "good"),
        (20.0, 1.2, "good"),
        (None, None, "no_signal"),
        (22.0, 0.8, "poor"),
    ]
    db.add_all(
        MinuteMetric(
            recording_id=first.id, minute_index=i, resp_rate_bpm=r, amplitude_rel=a, quality=q
        )
        for i, (r, a, q) in enumerate(minutes)
    )
    db.commit()

    store.save(f"waveforms/{RECORDING}.i16", breathing_i16().tobytes())
    meta = {
        "sample_rate_hz": SAMPLE_RATE_HZ, "offset": 4.1, "scale": 0.0001, "unit": "µH",
        "n_samples": N_SAMPLES, "missing_value": MISSING,
    }  # fmt: skip
    store.save(f"waveforms/{RECORDING}.json", json.dumps(meta).encode("utf-8"))
    return db


@pytest.fixture
def client(seeded: Session, store: LocalFileStore, engine: Engine) -> Iterator[TestClient]:
    """The app wired to the test database and store, with no API key required."""
    app.dependency_overrides[get_db] = lambda: seeded
    app.dependency_overrides[get_store] = lambda: store
    # Background processing opens its own session on the same test database.
    app.dependency_overrides[get_session_factory] = lambda: lambda: Session(engine)
    app.dependency_overrides[get_settings] = lambda: Settings(api_shared_secret=None)
    yield TestClient(app)
    app.dependency_overrides.clear()

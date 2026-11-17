"""The file store: where signal files live, behind a small interface.

Route code only calls `save`, `read_bytes` and `exists` with a path RELATIVE to the store
(for example "waveforms/NN-001_2026-09-14.i16"). Today the store is a folder on disk. Because
nothing else knows that, it can be swapped for a private Supabase Storage bucket later by
writing one more class with the same three methods.

Stored waveform format (the same one the static dashboard data uses):
    <code>.i16   int16 samples; value v means offset + v * scale; missing_value marks a gap
    <code>.json  {"sample_rate_hz", "offset", "scale", "unit", "n_samples", "missing_value"}
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol

import numpy as np

from .config import get_settings


class FileStore(Protocol):
    def save(self, relative_path: str, data: bytes) -> None: ...
    def read_bytes(self, relative_path: str) -> bytes: ...
    def exists(self, relative_path: str) -> bool: ...
    def save_stream(self, relative_path: str, source: BinaryIO, max_bytes: int) -> int: ...
    def move(self, source: str, target: str) -> None: ...
    def delete(self, relative_path: str) -> None: ...
    def local_path(self, relative_path: str) -> Path: ...


class LocalFileStore:
    """Files in a folder on this computer (api/file_store/ by default, gitignored)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        # Refuse paths like "../../secret" that would escape the store folder.
        if not path.is_relative_to(self.root):
            raise ValueError(f"path escapes the file store: {relative_path}")
        return path

    def save(self, relative_path: str, data: bytes) -> None:
        path = self._resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read_bytes(self, relative_path: str) -> bytes:
        return self._resolve(relative_path).read_bytes()

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).is_file()

    def save_stream(self, relative_path: str, source: BinaryIO, max_bytes: int) -> int:
        """Copy an upload to disk in 1 MB pieces, so a 60 MB file never sits in memory.

        Raises OverflowError (and removes the partial file) once it exceeds `max_bytes`.
        """
        path = self._resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("wb") as out:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    out.close()
                    path.unlink()
                    raise OverflowError("upload exceeds the size limit")
                out.write(chunk)
        return written

    def move(self, source: str, target: str) -> None:
        destination = self._resolve(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(self._resolve(source), destination)  # replaces an existing file

    def delete(self, relative_path: str) -> None:
        self._resolve(relative_path).unlink(missing_ok=True)

    def local_path(self, relative_path: str) -> Path:
        """A real path for code that needs a file on disk (the CSV reader).

        A remote store would download the file to a temporary folder here.
        """
        return self._resolve(relative_path)


@lru_cache
def _default_store() -> LocalFileStore:
    return LocalFileStore(get_settings().file_store_path)


def get_store() -> FileStore:
    """FastAPI dependency. Tests replace it with a store in a temporary folder."""
    return _default_store()


@dataclass
class Waveform:
    sample_rate_hz: float
    unit: str
    #: The signal in `unit`, one value per sample; NaN where the device lost samples.
    values: np.ndarray


def waveform_meta_path(waveform_path: str) -> str:
    return waveform_path.removesuffix(".i16") + ".json"


def load_waveform(store: FileStore, waveform_path: str) -> Waveform:
    meta = json.loads(store.read_bytes(waveform_meta_path(waveform_path)))
    packed = np.frombuffer(store.read_bytes(waveform_path), dtype="<i2")
    values = meta["offset"] + packed.astype(np.float64) * meta["scale"]
    values[packed == meta["missing_value"]] = np.nan
    return Waveform(float(meta["sample_rate_hz"]), meta["unit"], values)

"use client";

import { useSyncExternalStore } from "react";
import { type Annotation, sortAnnotations } from "./types";

// Where annotations live for the showcase build: this browser's localStorage, one key per
// recording. They survive reloads but aren't shared between people or devices.
// In Phase 3 this module is the only thing that changes (it will call the API instead).

const KEY_PREFIX = "nn.annotations.v1.";
const EMPTY: Annotation[] = [];

// Cached snapshots: useSyncExternalStore needs the SAME array back until something changes.
const cache = new Map<string, Annotation[]>();
const listeners = new Set<() => void>();

function read(recordingId: string): Annotation[] {
  const cached = cache.get(recordingId);
  if (cached) return cached;
  let list: Annotation[] = EMPTY;
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + recordingId);
    if (raw) list = sortAnnotations(JSON.parse(raw) as Annotation[]);
  } catch {
    // Storage blocked (private window) or corrupted: behave as if there are no notes.
  }
  cache.set(recordingId, list);
  return list;
}

function write(recordingId: string, list: Annotation[]) {
  const sorted = sortAnnotations(list);
  cache.set(recordingId, sorted);
  try {
    window.localStorage.setItem(KEY_PREFIX + recordingId, JSON.stringify(sorted));
  } catch {
    // Can't persist (quota/private mode); the notes still work until the page closes.
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Another tab changed storage: drop our cache so the next read picks it up.
  const onStorage = (e: StorageEvent) => {
    if (e.key?.startsWith(KEY_PREFIX)) {
      cache.delete(e.key.slice(KEY_PREFIX.length));
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The recording's annotations, sorted by time. Re-renders when they change. */
export function useAnnotations(recordingId: string): Annotation[] {
  return useSyncExternalStore(
    subscribe,
    () => read(recordingId),
    () => EMPTY, // the server has no localStorage
  );
}

export function addAnnotation(
  input: Omit<Annotation, "id" | "created_at" | "updated_at">,
): Annotation {
  const now = new Date().toISOString();
  const annotation: Annotation = { ...input, id: crypto.randomUUID(), created_at: now, updated_at: now };
  write(input.recording_id, [...read(input.recording_id), annotation]);
  return annotation;
}

export function updateAnnotation(
  recordingId: string,
  id: string,
  patch: Partial<Pick<Annotation, "category" | "note" | "start_ms" | "end_ms">>,
) {
  const now = new Date().toISOString();
  write(
    recordingId,
    read(recordingId).map((a) => (a.id === id ? { ...a, ...patch, updated_at: now } : a)),
  );
}

export function deleteAnnotation(recordingId: string, id: string) {
  write(recordingId, read(recordingId).filter((a) => a.id !== id));
}

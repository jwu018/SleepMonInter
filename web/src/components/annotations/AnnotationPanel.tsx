"use client";

import { useState } from "react";
import { addAnnotation, deleteAnnotation, updateAnnotation, useAnnotations } from "@/lib/annotations/store";
import { type Annotation, CATEGORIES, type Category, categoryLabel, NOTE_MAX_CHARS } from "@/lib/annotations/types";

// Clinician notes for one night: a form for the moment/stretch just picked on a chart, and
// the list of saved notes (numbered to match the flags drawn on the charts).

export interface PendingPick {
  start_ms: number;
  end_ms: number | null;
}

/** "2:31:05 AM" in the viewer's time zone. Only called in the browser. */
export function formatClock(startUtc: string, ms: number): string {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(
    new Date(Date.parse(startUtc) + ms),
  );
}

export function formatSpan(startUtc: string, startMs: number, endMs: number | null): string {
  return endMs === null
    ? `at ${formatClock(startUtc, startMs)}`
    : `${formatClock(startUtc, startMs)} – ${formatClock(startUtc, endMs)}`;
}

interface Props {
  recordingId: string;
  startUtc: string;
  authorEmail: string;
  pending: PendingPick | null;
  onClearPending: () => void;
  /** Show this time on the waveform. */
  onJump: (ms: number) => void;
}

export function AnnotationPanel({ recordingId, startUtc, authorEmail, pending, onClearPending, onJump }: Props) {
  const annotations = useAnnotations(recordingId);
  const [editingId, setEditingId] = useState<string | null>(null);

  return (
    <section className="space-y-3 rounded-lg border border-border p-4">
      <div>
        <h2 className="font-semibold">Clinician notes</h2>
        <p className="text-xs text-muted">
          Click a chart to mark a moment, or drag across it to mark a stretch. Saved in this browser only.
        </p>
      </div>

      {pending && (
        <div className="rounded-md border border-annotation/60 bg-annotation/5 p-3">
          <p className="mb-2 text-sm font-medium">New note {formatSpan(startUtc, pending.start_ms, pending.end_ms)}</p>
          <NoteForm
            submitLabel="Save note"
            onCancel={onClearPending}
            onSubmit={(category, note) => {
              addAnnotation({
                recording_id: recordingId,
                start_ms: pending.start_ms,
                end_ms: pending.end_ms,
                category,
                note,
                author_email: authorEmail,
              });
              onClearPending();
            }}
          />
        </div>
      )}

      {annotations.length === 0 ? (
        <p className="text-sm text-muted">No notes yet.</p>
      ) : (
        <ol className="space-y-2">
          {annotations.map((a, i) => (
            <li key={a.id} className="rounded-md border border-border p-2 text-sm">
              {editingId === a.id ? (
                <NoteForm
                  initial={a}
                  submitLabel="Save changes"
                  onCancel={() => setEditingId(null)}
                  onSubmit={(category, note) => {
                    updateAnnotation(recordingId, a.id, { category, note });
                    setEditingId(null);
                  }}
                />
              ) : (
                <AnnotationRow
                  number={i + 1}
                  annotation={a}
                  startUtc={startUtc}
                  onJump={() => onJump(a.start_ms)}
                  onEdit={() => setEditingId(a.id)}
                  onDelete={() => deleteAnnotation(recordingId, a.id)}
                />
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function AnnotationRow({
  number,
  annotation: a,
  startUtc,
  onJump,
  onEdit,
  onDelete,
}: {
  number: number;
  annotation: Annotation;
  startUtc: string;
  onJump: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="grid h-5 min-w-5 place-items-center rounded bg-annotation px-1 text-xs font-semibold text-white">
          {number}
        </span>
        <button type="button" onClick={onJump} className="text-accent hover:underline" title="Show on the waveform">
          {formatSpan(startUtc, a.start_ms, a.end_ms)}
        </button>
        <span className="rounded-full border border-border px-2 text-xs">{categoryLabel(a.category)}</span>
      </div>
      {a.note && <p className="whitespace-pre-wrap">{a.note}</p>}
      <div className="flex items-center gap-3 text-xs text-muted">
        <span>{a.author_email}</span>
        <button type="button" onClick={onEdit} className="hover:underline">
          Edit
        </button>
        <button type="button" onClick={onDelete} className="hover:underline">
          Delete
        </button>
      </div>
    </div>
  );
}

function NoteForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: Pick<Annotation, "category" | "note">;
  submitLabel: string;
  onSubmit: (category: Category, note: string) => void;
  onCancel: () => void;
}) {
  const [category, setCategory] = useState<Category>(initial?.category ?? "other");
  const [note, setNote] = useState(initial?.note ?? "");

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(category, note.trim());
      }}
    >
      <label className="block text-sm">
        <span className="text-muted">Category</span>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as Category)}
          className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-sm">
        <span className="text-muted">Note</span>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={NOTE_MAX_CHARS}
          rows={2}
          className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
          placeholder="e.g. rolled onto side, signal settles after"
        />
      </label>
      <div className="flex gap-2">
        <button type="submit" className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-background">
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} className="rounded-md border border-border px-3 py-1 text-sm hover:bg-surface">
          Cancel
        </button>
      </div>
    </form>
  );
}

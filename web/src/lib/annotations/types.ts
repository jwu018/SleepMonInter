// Clinician annotations: a note attached to a moment or a stretch of one recording.
// Times are ms since the recording started, like everywhere else in the app.

export const CATEGORIES = [
  { value: "artifact", label: "Artifact" },
  { value: "pause", label: "Pause" },
  { value: "position_change", label: "Position change" },
  { value: "review_with_family", label: "Review with family" },
  { value: "other", label: "Other" },
] as const;

export type Category = (typeof CATEGORIES)[number]["value"];

export const NOTE_MAX_CHARS = 500;

export interface Annotation {
  id: string;
  recording_id: string;
  start_ms: number;
  /** null = a single moment; otherwise the end of the marked stretch. */
  end_ms: number | null;
  category: Category;
  note: string;
  author_email: string;
  created_at: string; // ISO, UTC
  updated_at: string;
}

export function categoryLabel(value: Category): string {
  return CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

/** Sorted by time, so the numbers shown on the charts match the list. */
export function sortAnnotations(list: Annotation[]): Annotation[] {
  return [...list].sort((a, b) => a.start_ms - b.start_ms || a.created_at.localeCompare(b.created_at));
}

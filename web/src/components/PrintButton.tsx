"use client";

// window.print() only exists in the browser, so this button is a client component.
export function PrintButton() {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-background"
    >
      Print
    </button>
  );
}

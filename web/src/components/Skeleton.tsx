// Grey placeholder blocks shown while a Suspense boundary waits for data.

export function TableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="animate-pulse space-y-2" aria-label="Loading">
      {Array.from({ length: rows + 1 }, (_, i) => (
        <div key={i} className="h-10 rounded bg-surface" />
      ))}
    </div>
  );
}

export function BlockSkeleton({ height = 200 }: { height?: number }) {
  return <div className="animate-pulse rounded-lg bg-surface" style={{ height }} aria-label="Loading" />;
}

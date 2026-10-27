// Turn whatever the user picked or dropped into a flat list of files with their paths.
// Browser-only (uses the drag-and-drop file APIs).

export interface PickedFile {
  file: File;
  /** Path inside the picked folder, e.g. "NIGHTNIGHT/S20261026_205511.csv". */
  path: string;
}

/** From <input type="file"> (single files, or a whole folder with webkitdirectory). */
export function fromFileList(list: FileList | null): PickedFile[] {
  return Array.from(list ?? [], (file) => ({ file, path: file.webkitRelativePath || file.name }));
}

/** From a drop event. Dropped folders are walked recursively. */
export async function fromDataTransfer(dt: DataTransfer): Promise<PickedFile[]> {
  // Grab the entries synchronously: the browser empties the DataTransfer after the event.
  const entries = Array.from(dt.items)
    .map((item) => item.webkitGetAsEntry())
    .filter((e): e is FileSystemEntry => e !== null);
  if (entries.length === 0) return fromFileList(dt.files);

  const out: PickedFile[] = [];
  await Promise.all(entries.map((entry) => walk(entry, "", out)));
  return out;
}

async function walk(entry: FileSystemEntry, prefix: string, out: PickedFile[]): Promise<void> {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject),
    );
    out.push({ file, path });
    return;
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries returns results in batches; keep calling until it returns an empty batch.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject),
      );
      if (batch.length === 0) break;
      await Promise.all(batch.map((child) => walk(child, path, out)));
    }
  }
}

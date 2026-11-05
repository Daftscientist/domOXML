// Document store: decks live in the browser's Origin Private File
// System, one JSON file per document under /decks. The stored form is
// the deck document itself (size, stylesheet, per-slide HTML and
// transitions) — the same data opening a .pptx produces — so a stored
// file reopens exactly as it was, and exporting it needs no storage
// round trip. Grid and Write documents will get their own directories
// alongside this one when those editors land.
import type { Deck } from "./types";

export type DocKind = "deck";

export interface DocMeta {
  id: string;
  kind: DocKind;
  name: string;
  slideCount: number;
  width: number;
  height: number;
  createdAt: number;
  updatedAt: number;
}

interface StoredDoc {
  version: 1;
  kind: DocKind;
  createdAt: number;
  updatedAt: number;
  deck: Deck;
}

const DIR = "decks";

async function docsDir(): Promise<FileSystemDirectoryHandle> {
  const root = await navigator.storage.getDirectory();
  return root.getDirectoryHandle(DIR, { create: true });
}

function metaOf(stored: StoredDoc): DocMeta {
  return {
    id: stored.deck.id,
    kind: stored.kind,
    name: stored.deck.name,
    slideCount: stored.deck.slides.length,
    width: stored.deck.width,
    height: stored.deck.height,
    createdAt: stored.createdAt,
    updatedAt: stored.updatedAt,
  };
}

async function readStored(id: string): Promise<StoredDoc | null> {
  try {
    const dir = await docsDir();
    const handle = await dir.getFileHandle(`${id}.json`);
    const text = await (await handle.getFile()).text();
    const parsed = JSON.parse(text) as StoredDoc;
    if (parsed.version !== 1 || !parsed.deck) return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function listDocs(): Promise<DocMeta[]> {
  const metas: DocMeta[] = [];
  try {
    const dir = await docsDir();
    // Directory iteration is async; the DOM lib types lag the spec, so
    // the iterator is taken through a narrow cast.
    const iterable = dir as unknown as {
      values(): AsyncIterable<FileSystemHandle>;
    };
    for await (const handle of iterable.values()) {
      if (handle.kind !== "file" || !handle.name.endsWith(".json")) continue;
      try {
        const file = await (handle as FileSystemFileHandle).getFile();
        const parsed = JSON.parse(await file.text()) as StoredDoc;
        if (parsed.version === 1 && parsed.deck) metas.push(metaOf(parsed));
      } catch {
        // A corrupt entry must not hide the rest of the library.
      }
    }
  } catch {
    // OPFS unavailable (rare): the library simply reads as empty.
  }
  return metas.sort((a, b) => b.updatedAt - a.updatedAt);
}

export async function getDoc(id: string): Promise<Deck | null> {
  const stored = await readStored(id);
  return stored?.deck ?? null;
}

export async function putDoc(deck: Deck): Promise<DocMeta> {
  // Best effort: ask the browser to keep the origin's storage around.
  void navigator.storage.persist?.().catch(() => false);
  const existing = await readStored(deck.id);
  const now = Date.now();
  const stored: StoredDoc = {
    version: 1,
    kind: "deck",
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
    deck,
  };
  const dir = await docsDir();
  const handle = await dir.getFileHandle(`${deck.id}.json`, { create: true });
  const writable = await handle.createWritable();
  await writable.write(JSON.stringify(stored));
  await writable.close();
  return metaOf(stored);
}

export async function removeDoc(id: string): Promise<void> {
  try {
    const dir = await docsDir();
    await dir.removeEntry(`${id}.json`);
  } catch {
    // Already gone; deletion is idempotent from the UI's perspective.
  }
}

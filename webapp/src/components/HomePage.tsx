import { useRef, useState } from "react";
import {
  FilePlus2, FolderOpen, LayoutGrid, Moon, PenLine, Presentation, Sun, Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { DocMeta } from "@/lib/store";
import { cn } from "@/lib/utils";

interface Props {
  docs: DocMeta[];
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onCreateBlank: () => void;
  onCreateSample: () => void;
  onOpenFile: (file: File) => void;
  dark: boolean;
  onToggleTheme: () => void;
}

function editedAgo(updatedAt: number): string {
  const seconds = Math.max(0, Math.floor((Date.now() - updatedAt) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(updatedAt).toLocaleDateString();
}

export function HomePage(p: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-4 py-8 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Presentation className="h-4.5 w-4.5" />
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-lg font-semibold tracking-tight">domOXML</span>
            <span className="text-sm text-muted-foreground">Studio</span>
          </div>
          <div className="flex-1" />
          <Button
            variant="ghost"
            size="icon"
            onClick={p.onToggleTheme}
            aria-label="Toggle colour theme"
            className="h-8 w-8"
          >
            {p.dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>

        <section>
          <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
            Create new
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="flex flex-col">
              <button
                onClick={p.onCreateBlank}
                className="group flex flex-1 flex-col items-start gap-3 rounded-xl border bg-card p-5 text-left shadow-sm transition-colors hover:border-primary/50 hover:bg-accent/40"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Presentation className="h-5 w-5" />
                </span>
                <span>
                  <span className="block text-[15px] font-medium">Deck</span>
                  <span className="mt-1 block text-[13px] leading-relaxed text-muted-foreground">
                    Slides designed in HTML, exported as a real, editable PowerPoint.
                  </span>
                </span>
                <span className="mt-auto inline-flex items-center gap-1 text-[13px] font-medium text-primary">
                  <FilePlus2 className="h-3.5 w-3.5" /> New deck
                </span>
              </button>
              <button
                onClick={p.onCreateSample}
                className="mt-2 self-start text-[13px] text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                or start from the sample deck
              </button>
            </div>

            {[
              { icon: LayoutGrid, name: "Grid", blurb: "Spreadsheets, in the same document family." },
              { icon: PenLine, name: "Write", blurb: "Long-form documents, in the same document family." },
            ].map(({ icon: Icon, name, blurb }) => (
              <div
                key={name}
                className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-card/40 p-5 text-left opacity-70"
                aria-disabled="true"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <Icon className="h-5 w-5" />
                </span>
                <span>
                  <span className="block text-[15px] font-medium">{name}</span>
                  <span className="mt-1 block text-[13px] leading-relaxed text-muted-foreground">
                    {blurb}
                  </span>
                </span>
                <Badge variant="secondary" className="mt-auto font-normal">
                  Coming soon
                </Badge>
              </div>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4 shadow-sm">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <FolderOpen className="h-4.5 w-4.5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">Open a PowerPoint file</p>
              <p className="text-[13px] text-muted-foreground">
                Brought in as an editable deck and saved to your files below.
              </p>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) p.onOpenFile(file);
                e.target.value = "";
              }}
            />
            <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
              Choose .pptx
            </Button>
          </div>
        </section>

        <section>
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
              Your files
            </h2>
            <span className="text-xs text-muted-foreground">
              Stored in this browser, on this device
            </span>
          </div>
          {p.docs.length === 0 ? (
            <div className="mt-3 rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
              Nothing saved yet. Create a deck or open a .pptx and it will be here next time you visit.
            </div>
          ) : (
            <ul className="mt-3 flex flex-col gap-2">
              {p.docs.map((doc) => (
                <li
                  key={doc.id}
                  className={cn(
                    "group flex items-center gap-3 rounded-xl border bg-card p-3.5 shadow-sm transition-colors",
                    "hover:border-primary/50",
                  )}
                >
                  <button
                    onClick={() => p.onOpen(doc.id)}
                    className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Presentation className="h-4.5 w-4.5" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{doc.name}</span>
                      <span className="block text-xs text-muted-foreground">
                        Deck · {doc.slideCount} {doc.slideCount === 1 ? "slide" : "slides"} ·{" "}
                        {doc.width} × {doc.height} · Edited {editedAgo(doc.updatedAt)}
                      </span>
                    </span>
                  </button>
                  {confirmDelete === doc.id ? (
                    <span className="flex shrink-0 items-center gap-1.5">
                      <Button
                        variant="destructive"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => {
                          p.onDelete(doc.id);
                          setConfirmDelete(null);
                        }}
                      >
                        Delete
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => setConfirmDelete(null)}
                      >
                        Keep
                      </Button>
                    </span>
                  ) : (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                      aria-label={`Delete ${doc.name}`}
                      onClick={() => setConfirmDelete(doc.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

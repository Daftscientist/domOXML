import { useCallback, useEffect, useMemo, useState } from "react";
import { FilePlus2, Layers, MonitorPlay, PencilRuler, Presentation } from "lucide-react";
import { toast, Toaster } from "sonner";
import { EditProvider } from "@pierre/diffs/react";
import { Editor } from "@pierre/diffs/edit";
import type { EditorFactory } from "@pierre/diffs/react";
import { Header } from "@/components/Header";
import { SlideRail } from "@/components/SlideRail";
import { Stage } from "@/components/Stage";
import { Inspector } from "@/components/Inspector";
import { PresentMode } from "@/components/PresentMode";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { engine } from "@/lib/engine";
import { downloadBytes, downloadText, slug } from "@/lib/download";
import { blankSlideHtml, newSlideId, sampleDeck } from "@/lib/sample";
import type { ConvertResult, Deck, SlideTransition } from "@/lib/types";
import { cn } from "@/lib/utils";

type MobileTab = "slides" | "preview" | "edit";

// One stable editor factory for the Pierre code surfaces (slide HTML and
// the deck stylesheet). Each surface gets its own Editor instance.
const createEditor: EditorFactory<undefined, undefined> = (type, options, key) =>
  new Editor(type, options, key);

export default function App() {
  const [deck, setDeck] = useState<Deck>(() => sampleDeck());
  const [selected, setSelected] = useState(0);
  const [dark, setDark] = useState<boolean>(() => {
    const saved = localStorage.getItem("domoxml-theme");
    if (saved) return saved === "dark";
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  });
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<ConvertResult | null>(null);
  const [presenting, setPresenting] = useState(false);
  const [confirmNew, setConfirmNew] = useState(false);
  const [mobileTab, setMobileTab] = useState<MobileTab>("preview");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("domoxml-theme", dark ? "dark" : "light");
  }, [dark]);

  const patchSlide = useCallback(
    (index: number, patch: Partial<Deck["slides"][number]>) => {
      setDeck((d) => ({
        ...d,
        slides: d.slides.map((s, i) => (i === index ? { ...s, ...patch } : s)),
      }));
    },
    [],
  );

  const addSlide = useCallback(() => {
    setDeck((d) => {
      const slides = [
        ...d.slides.slice(0, selected + 1),
        { id: newSlideId(), html: blankSlideHtml(d.width, d.height), transition: null },
        ...d.slides.slice(selected + 1),
      ];
      return { ...d, slides };
    });
    setSelected((s) => s + 1);
  }, [selected]);

  const duplicateSlide = useCallback((index: number) => {
    setDeck((d) => ({
      ...d,
      slides: [
        ...d.slides.slice(0, index + 1),
        { ...d.slides[index], id: newSlideId() },
        ...d.slides.slice(index + 1),
      ],
    }));
    setSelected(index + 1);
  }, []);

  const deleteSlide = useCallback((index: number) => {
    setDeck((d) => ({ ...d, slides: d.slides.filter((_, i) => i !== index) }));
    setSelected((s) => Math.max(0, Math.min(s, deck.slides.length - 2)));
  }, [deck.slides.length]);

  const exportPptx = useCallback(async () => {
    setExporting(true);
    try {
      const result = await engine.convert(
        deck.slides.map((s) => s.html),
        {
          width: deck.width,
          height: deck.height,
          css: deck.css,
          transitions: deck.slides.map((s) => s.transition),
        },
      );
      downloadBytes(
        `${slug(deck.name)}.pptx`,
        result.pptx,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      );
      setExportResult(result);
    } catch (error) {
      toast.error("Export failed", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setExporting(false);
    }
  }, [deck]);

  const downloadHtml = useCallback(() => {
    const slides = deck.slides
      .map(
        (s) =>
          `<div class="slide" style="width:${deck.width}px;height:${deck.height}px;position:relative;overflow:hidden">${s.html}</div>`,
      )
      .join("\n");
    const doc = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${deck.name}</title>
<style>
${deck.css}
body { margin: 0; background: #525252; display: flex; flex-direction: column; align-items: center; gap: 24px; padding: 24px; }
.slide { background: white; flex: none; }
.slide > section { width: 100% !important; height: 100% !important; }
</style>
</head>
<body>
${slides}
</body>
</html>`;
    downloadText(`${slug(deck.name)}.html`, doc);
  }, [deck]);

  const openFile = useCallback(async (file: File) => {
    try {
      const data = new Uint8Array(await file.arrayBuffer());
      const result = await engine.readDeck(data);
      if (result.slides.length === 0) {
        toast.error("That file has no slides we can read");
        return;
      }
      setDeck({
        id: newSlideId(),
        name: file.name.replace(/\.pptx$/i, ""),
        width: result.width,
        height: result.height,
        css: result.css,
        slides: result.slides.map((s) => ({
          id: newSlideId(),
          html: s.html,
          transition: s.transition,
        })),
      });
      setSelected(0);
      setMobileTab("preview");
      toast.success(`Opened ${file.name}`, {
        description: `${result.slides.length} slides · ${result.width} × ${result.height}`,
      });
    } catch (error) {
      toast.error("Could not open that file", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  }, []);

  const newDeck = useCallback(() => {
    setDeck({
      id: newSlideId(),
      name: "Untitled presentation",
      width: 1280,
      height: 720,
      css: deck.css,
      slides: [{ id: newSlideId(), html: blankSlideHtml(1280, 720), transition: null }],
    });
    setSelected(0);
    setConfirmNew(false);
  }, [deck.css]);

  const editableShare = useMemo(() => {
    if (!exportResult || exportResult.coverage.length === 0) return null;
    const native = exportResult.coverage.filter((c) => c.representation === "native").length;
    return { native, total: exportResult.coverage.length, pct: Math.round((native / exportResult.coverage.length) * 100) };
  }, [exportResult]);

  return (
    <EditProvider createEditor={createEditor}>
    <div className="flex h-full flex-col bg-background text-foreground">
      <Header
        name={deck.name}
        onNameChange={(name) => setDeck((d) => ({ ...d, name }))}
        slideCount={deck.slides.length}
        dark={dark}
        onToggleTheme={() => setDark((v) => !v)}
        exporting={exporting}
        onExportPptx={exportPptx}
        onDownloadHtml={downloadHtml}
        onOpenFile={openFile}
        onPresent={() => setPresenting(true)}
      />

      <div className="flex min-h-0 flex-1">
        <div
          className={cn(
            "w-60 shrink-0 border-r max-lg:absolute max-lg:inset-x-0 max-lg:bottom-14 max-lg:top-[52px] max-lg:z-20 max-lg:w-full max-lg:bg-background",
            mobileTab !== "slides" && "max-lg:hidden",
          )}
        >
          <SlideRail
            deck={deck}
            selected={selected}
            onSelect={(i) => { setSelected(i); setMobileTab("preview"); }}
            onAdd={addSlide}
            onDuplicate={duplicateSlide}
            onDelete={deleteSlide}
          />
        </div>

        <div className={cn("min-w-0 flex-1", mobileTab !== "preview" && "max-lg:hidden")}>
          <Stage deck={deck} selected={selected} onSelect={setSelected} />
        </div>

        <div
          className={cn(
            "flex w-[400px] shrink-0 flex-col border-l max-lg:absolute max-lg:inset-x-0 max-lg:bottom-14 max-lg:top-[52px] max-lg:z-20 max-lg:w-full max-lg:bg-background",
            mobileTab !== "edit" && "max-lg:hidden",
          )}
        >
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              <PencilRuler className="h-3.5 w-3.5" /> Inspector
            </span>
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setConfirmNew(true)}>
              <FilePlus2 className="h-3.5 w-3.5" /> New deck
            </Button>
          </div>
          <div className="min-h-0 flex-1">
            <Inspector
              deck={deck}
              selected={selected}
              dark={dark}
              onSlideHtml={(html) => patchSlide(selected, { html })}
              onSlideTransition={(transition) => patchSlide(selected, { transition })}
              onDeckChange={(patch) => setDeck((d) => ({ ...d, ...patch }))}
              onApplyTransitionToAll={(transition) =>
                setDeck((d) => ({ ...d, slides: d.slides.map((s) => ({ ...s, transition })) }))
              }
            />
          </div>
        </div>
      </div>

      <nav className="flex h-14 shrink-0 items-stretch justify-around border-t bg-background lg:hidden">
        {(
          [
            { key: "slides", label: "Slides", icon: Layers },
            { key: "preview", label: "Preview", icon: Presentation },
            { key: "edit", label: "Edit", icon: PencilRuler },
          ] as const
        ).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setMobileTab(key)}
            className={cn(
              "flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]",
              mobileTab === key ? "font-medium text-foreground" : "text-muted-foreground",
            )}
          >
            <Icon className="h-5 w-5" />
            {label}
          </button>
        ))}
        <button
          onClick={() => setPresenting(true)}
          className="flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground"
        >
          <MonitorPlay className="h-5 w-5" />
          Present
        </button>
      </nav>

      {presenting && (
        <PresentMode deck={deck} startAt={selected} onClose={() => setPresenting(false)} />
      )}

      <Dialog open={exportResult !== null} onOpenChange={(open) => !open && setExportResult(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Export complete</DialogTitle>
            <DialogDescription>
              {deck.name}.pptx has been downloaded. Here is how the deck was built:
            </DialogDescription>
          </DialogHeader>
          {editableShare && (
            <div className="flex flex-col gap-3">
              <div>
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-medium">Editable in PowerPoint</span>
                  <span className="text-sm tabular-nums text-muted-foreground">
                    {editableShare.native} of {editableShare.total} elements · {editableShare.pct}%
                  </span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-emerald-500" style={{ width: `${editableShare.pct}%` }} />
                </div>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  Native elements stay editable as text and shapes. Anything Takumi paints
                  that has no PowerPoint equivalent yet is kept as one picture per slide,
                  never as cropped fragments.
                </p>
              </div>
              {exportResult && exportResult.warnings.length > 0 && (
                <div className="max-h-40 overflow-y-auto rounded-lg border bg-muted/40 p-3">
                  <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Warnings ({exportResult.warnings.length})
                  </p>
                  <ul className="flex flex-col gap-1 text-xs leading-relaxed">
                    {exportResult.warnings.slice(0, 12).map((w, i) => (
                      <li key={i}><span className="font-medium">{w.element}:</span> {w.message}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setExportResult(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmNew} onOpenChange={setConfirmNew}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Start a new presentation?</DialogTitle>
            <DialogDescription>
              The current deck is not saved anywhere. Export it first if you want to keep it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmNew(false)}>Keep editing</Button>
            <Button variant="destructive" onClick={newDeck}>Discard and start new</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Toaster position="bottom-center" richColors={false} />
    </div>
    </EditProvider>
  );
}

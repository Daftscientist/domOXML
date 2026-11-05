import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FilePlus2, Layers, MonitorPlay, PencilRuler, Presentation } from "lucide-react";
import { toast, Toaster } from "sonner";
import { EditProvider } from "@pierre/diffs/react";
import { Editor } from "@pierre/diffs/edit";
import type { EditorFactory } from "@pierre/diffs/react";
import { Header } from "@/components/Header";
import { HomePage } from "@/components/HomePage";
import { SlideRail } from "@/components/SlideRail";
import { Stage } from "@/components/Stage";
import { Inspector } from "@/components/Inspector";
import { PresentMode } from "@/components/PresentMode";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { engine } from "@/lib/engine";
import { captureOneSlide, exportViaHostCapture } from "@/lib/hostCapture";
import { downloadBytes, downloadText, slug } from "@/lib/download";
import { isForeignFragment } from "@/lib/normalize";
import { mutateFragment, type SlideMutation } from "@/lib/fragmentEdit";
import { blankSlideHtml, DEFAULT_CSS, newSlideId, sampleDeck } from "@/lib/sample";
import { getDoc, listDocs, putDoc, removeDoc } from "@/lib/store";
import type { DocMeta } from "@/lib/store";
import type { IrDeriveState } from "@/components/IrTree";
import type { ConvertResult, Deck, SlideIrResult, SlideTransition } from "@/lib/types";
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
  const [mobileTab, setMobileTab] = useState<MobileTab>("preview");
  // Home (the file library) vs the editor. Documents live in OPFS (see
  // lib/store); the open document autosaves back there as it changes.
  const [view, setView] = useState<"home" | "editor">("home");
  const [docs, setDocs] = useState<DocMeta[]>([]);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const lastSavedJsonRef = useRef<string>("");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("domoxml-theme", dark ? "dark" : "light");
  }, [dark]);

  const refreshDocs = useCallback(async () => {
    setDocs(await listDocs());
  }, []);

  useEffect(() => {
    void refreshDocs();
  }, [refreshDocs]);

  const upsertMeta = useCallback((meta: DocMeta) => {
    setDocs((prev) => [meta, ...prev.filter((m) => m.id !== meta.id)]);
  }, []);

  const enterEditor = useCallback((d: Deck) => {
    lastSavedJsonRef.current = JSON.stringify(d);
    setDeck(d);
    setSelected(0);
    setMobileTab("preview");
    setActiveDocId(d.id);
    setSaveState("saved");
    setView("editor");
  }, []);

  /** Store a freshly built deck as a library document, then open it. */
  const createAndOpen = useCallback(
    async (d: Deck) => {
      try {
        upsertMeta(await putDoc(d));
      } catch {
        // Storage failing must not block opening the document.
      }
      enterEditor(d);
    },
    [enterEditor, upsertMeta],
  );

  const openStored = useCallback(
    async (id: string) => {
      const d = await getDoc(id);
      if (!d) {
        toast.error("Could not open that file", {
          description: "It may have been removed from this browser's storage.",
        });
        void refreshDocs();
        return;
      }
      enterEditor(d);
    },
    [enterEditor, refreshDocs],
  );

  const goHome = useCallback(async () => {
    // Flush the open document before leaving it.
    if (activeDocId && deck.id === activeDocId) {
      try {
        upsertMeta(await putDoc(deck));
        lastSavedJsonRef.current = JSON.stringify(deck);
      } catch {
        // The debounced autosave remains as a backstop.
      }
    }
    setActiveDocId(null);
    setView("home");
    void refreshDocs();
  }, [activeDocId, deck, refreshDocs, upsertMeta]);

  const deleteStored = useCallback(
    async (id: string) => {
      await removeDoc(id);
      setDocs((prev) => prev.filter((m) => m.id !== id));
      toast.success("Deleted from your files");
    },
    [],
  );

  // Autosave the open document (debounced; skipped when nothing changed
  // since the last write, e.g. straight after opening it).
  useEffect(() => {
    if (view !== "editor" || !activeDocId || deck.id !== activeDocId) return;
    if (JSON.stringify(deck) === lastSavedJsonRef.current) return;
    setSaveState("saving");
    const t = setTimeout(async () => {
      try {
        const meta = await putDoc(deck);
        lastSavedJsonRef.current = JSON.stringify(deck);
        setSaveState("saved");
        upsertMeta(meta);
      } catch {
        setSaveState("idle");
      }
    }, 700);
    return () => clearTimeout(t);
  }, [deck, view, activeDocId, upsertMeta]);

  // The selected element on the open slide, as a DOM path from the
  // composed page's body. Shared by the stage editor (which sets it by
  // hit-testing) and the IR tree (which sets it by row click); each
  // side highlights from the same value.
  const [focusPath, setFocusPath] = useState<number[] | null>(null);
  useEffect(() => {
    setFocusPath(null);
  }, [selected, deck.id]);

  // Visual edits from the stage, committed into the slide's HTML.
  // The code editor owns its document while mounted (see CodeEditor),
  // so a programmatic change to the slide HTML — a stage gesture or a
  // normalisation — must remount it under a fresh key, or it would keep
  // showing (and on the next keystroke, restore) the stale document.
  const [slideEpoch, setSlideEpoch] = useState(0);
  const [cssEpoch, setCssEpoch] = useState(0);

  const mutateSelectedSlide = useCallback(
    (path: number[], mutation: SlideMutation) => {
      const slide = deckRef.current.slides[selected];
      if (!slide) return;
      const next = mutateFragment(slide.html, path, mutation);
      if (next === null || next === slide.html) return;
      setSlideEpoch((e) => e + 1);
      setDeck((d) => ({
        ...d,
        slides: d.slides.map((s, i) =>
          i === selected ? { ...s, html: next } : s,
        ),
      }));
    },
    [selected],
  );

  // Normalisation: foreign HTML (hand-authored, flow layout, classes)
  // only means something once a browser has laid it out. Running it
  // through capture + extraction + serialisation replaces it with the
  // canonical domOXML fragment — fully geometric, parseable straight
  // back to IR with no browser. Triggered by a paste that dominates
  // the slide (an import, in effect) or manually from the Slide tab;
  // ordinary edits and already-normalised slides are never touched.
  const deckRef = useRef(deck);
  deckRef.current = deck;
  const normaliseSeq = useRef(0);
  const runNormalise = useCallback(
    async (slideIndex: number, sourceHtml: string, reason: "paste" | "manual") => {
      const seq = ++normaliseSeq.current;
      try {
        const capture = await captureOneSlide(sourceHtml, {
          width: deck.width,
          height: deck.height,
          css: deck.css,
        });
        const out = await engine.normalize(capture, {
          width: deck.width,
          height: deck.height,
        });
        if (normaliseSeq.current !== seq) return;
        const slide = deckRef.current.slides[slideIndex];
        if (!slide || slide.html !== sourceHtml) return; // edited since; leave it
        const cssChanged = !!out.css && !deckRef.current.css.includes(out.css.trim());
        setSlideEpoch((e) => e + 1);
        if (cssChanged) setCssEpoch((e) => e + 1);
        setDeck((d) => ({
          ...d,
          css: cssChanged ? `${d.css}\n${out.css}` : d.css,
          slides: d.slides.map((s, i) =>
            i === slideIndex ? { ...s, html: out.html } : s,
          ),
        }));
        toast.success(
          reason === "paste"
            ? "Pasted HTML converted to native domOXML"
            : "Slide rebuilt as native domOXML",
          {
            description:
              "Every element is now a positioned shape, so this slide opens, edits and exports without a browser layout pass.",
          },
        );
      } catch (error) {
        // A failed paste conversion stays silent: the pasted HTML still
        // works through the browser path. The manual action reports.
        if (reason === "manual") {
          toast.error("Could not rebuild that slide", {
            description: error instanceof Error ? error.message : String(error),
          });
        }
      }
    },
    [deck.width, deck.height, deck.css],
  );

  const pendingPasteRef = useRef<{
    slideId: string;
    clipLength: number;
    at: number;
  } | null>(null);
  const noteHtmlPaste = useCallback(
    (clipLength: number) => {
      const slide = deckRef.current.slides[selected];
      if (slide) {
        pendingPasteRef.current = { slideId: slide.id, clipLength, at: Date.now() };
      }
    },
    [selected],
  );

  // A native capture-phase listener: paste events inside the code
  // editor (a shadow-DOM component) are reliably visible here with
  // their clipboard data, whatever the editor does with them after.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const inEditor = e
        .composedPath()
        .some(
          (n) =>
            n instanceof HTMLElement && n.dataset && "htmlEditor" in n.dataset,
        );
      if (!inEditor) return;
      noteHtmlPaste(e.clipboardData?.getData("text/plain")?.length ?? 0);
    };
    document.addEventListener("paste", onPaste, true);
    return () => document.removeEventListener("paste", onPaste, true);
  }, [noteHtmlPaste]);

  // The selected slide's IR, derived automatically in the background:
  // host-capture the live slide and run the desktop extraction over it
  // whenever the slide settles. Stale results are dropped by sequence.
  const [irState, setIrState] = useState<IrDeriveState>("idle");
  const [irResult, setIrResult] = useState<SlideIrResult | null>(null);
  const [irError, setIrError] = useState<string | undefined>(undefined);
  const deriveSeq = useRef(0);
  const selectedHtml = deck.slides[selected]?.html;
  useEffect(() => {
    if (view !== "editor" || !selectedHtml) return;
    const seq = ++deriveSeq.current;
    setIrState("deriving");
    const t = setTimeout(async () => {
      try {
        const capture = await captureOneSlide(selectedHtml, {
          width: deck.width,
          height: deck.height,
          css: deck.css,
        });
        const result = await engine.slideIr(capture, {
          width: deck.width,
          height: deck.height,
        });
        if (deriveSeq.current !== seq) return;
        setIrResult(result);
        setIrState("ready");
        setIrError(undefined);
      } catch (error) {
        if (deriveSeq.current !== seq) return;
        setIrState("error");
        setIrError(error instanceof Error ? error.message : String(error));
      }
    }, 650);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedHtml, deck.css, deck.width, deck.height, selected, deck.id]);

  // After a paste into the HTML editor: if the pasted content dominates
  // the slide and the result is foreign HTML, normalise it seamlessly.
  useEffect(() => {
    const pending = pendingPasteRef.current;
    if (!pending || view !== "editor" || !selectedHtml) return;
    const slide = deck.slides[selected];
    if (!slide || slide.id !== pending.slideId) return;
    if (Date.now() - pending.at > 5000) {
      pendingPasteRef.current = null;
      return;
    }
    if (pending.clipLength < selectedHtml.length * 0.5) return;
    if (!isForeignFragment(selectedHtml)) {
      pendingPasteRef.current = null;
      return;
    }
    pendingPasteRef.current = null;
    void runNormalise(selected, selectedHtml, "paste");
  }, [selectedHtml, selected, deck.slides, view, runNormalise]);

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
      const fragments = deck.slides.map((s) => s.html);
      const opts = {
        width: deck.width,
        height: deck.height,
        css: deck.css,
        transitions: deck.slides.map((s) => s.transition),
      };
      // Host capture first: the browser lays the slides out itself, so
      // CSS Takumi cannot parse still converts. Any failure falls back
      // to the Takumi conversion, so export never regresses below it.
      let result: ConvertResult;
      try {
        result = await exportViaHostCapture({ fragments, ...opts });
      } catch (captureError) {
        console.warn("Host-capture export failed; falling back to Takumi", captureError);
        result = await engine.convert(fragments, opts);
      }
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
      // The deck is read into its document form (size, stylesheet,
      // per-slide HTML) and stored in the library, so it reopens from
      // Your files without the original .pptx.
      await createAndOpen({
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
      toast.success(`Opened ${file.name}`, {
        description: `${result.slides.length} slides · ${result.width} × ${result.height} · Saved to your files`,
      });
    } catch (error) {
      toast.error("Could not open that file", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  }, [createAndOpen]);

  /** A new blank deck as a stored document (from Home or the editor). */
  const newDeck = useCallback(() => {
    void createAndOpen({
      id: newSlideId(),
      name: "Untitled presentation",
      width: 1280,
      height: 720,
      css: DEFAULT_CSS,
      slides: [{ id: newSlideId(), html: blankSlideHtml(1280, 720), transition: null }],
    });
  }, [createAndOpen]);

  const sampleAsDoc = useCallback(() => {
    void createAndOpen(sampleDeck());
  }, [createAndOpen]);

  const editableShare = useMemo(() => {
    if (!exportResult || exportResult.coverage.length === 0) return null;
    const native = exportResult.coverage.filter((c) => c.representation === "native").length;
    return { native, total: exportResult.coverage.length, pct: Math.round((native / exportResult.coverage.length) * 100) };
  }, [exportResult]);

  return (
    <EditProvider createEditor={createEditor}>
    <div className="flex h-full flex-col bg-background text-foreground">
      {view === "home" ? (
        <HomePage
          docs={docs}
          onOpen={(id) => void openStored(id)}
          onDelete={(id) => void deleteStored(id)}
          onCreateBlank={newDeck}
          onCreateSample={sampleAsDoc}
          onOpenFile={openFile}
          dark={dark}
          onToggleTheme={() => setDark((v) => !v)}
        />
      ) : (
      <>
      <Header
        name={deck.name}
        onNameChange={(name) => setDeck((d) => ({ ...d, name }))}
        onHome={() => void goHome()}
        saveState={saveState}
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
          <Stage
            deck={deck}
            selected={selected}
            onSelect={setSelected}
            focusPath={focusPath}
            onFocusPath={setFocusPath}
            onMutate={mutateSelectedSlide}
          />
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
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={newDeck}>
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
              irState={irState}
              irResult={irResult}
              irError={irError}
              focusPath={focusPath}
              onFocusPath={setFocusPath}
              slideEditorKey={`slide:${deck.slides[selected]?.id ?? "none"}:e${slideEpoch}`}
              cssEditorKey={`css:${deck.id}:e${cssEpoch}`}
              onNormaliseSlide={() => {
                const slide = deck.slides[selected];
                if (slide) void runNormalise(selected, slide.html, "manual");
              }}
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
      </>
      )}

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
                  Native elements stay editable as text and shapes. Anything with no
                  PowerPoint equivalent yet is kept as a picture, never as cropped
                  fragments.
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

      <Toaster position="bottom-center" richColors={false} />
    </div>
    </EditProvider>
  );
}

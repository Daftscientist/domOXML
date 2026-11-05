import { useState } from "react";
import { FileCode2, Shapes } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CodeEditor } from "./CodeEditor";
import { IrTree, type IrDeriveState } from "./IrTree";
import { downloadText, slug } from "@/lib/download";
import { isForeignFragment, isNormalisedFragment } from "@/lib/normalize";
import {
  SIZE_PRESETS, TRANSITION_DIRECTIONS, TRANSITION_TYPES,
  type Deck, type SlideIrResult, type SlideTransition, type TransitionType,
} from "@/lib/types";

interface Props {
  deck: Deck;
  selected: number;
  dark: boolean;
  onSlideHtml: (html: string) => void;
  onSlideTransition: (t: SlideTransition | null) => void;
  onDeckChange: (patch: Partial<Deck>) => void;
  onApplyTransitionToAll: (t: SlideTransition | null) => void;
  irState: IrDeriveState;
  irResult: SlideIrResult | null;
  irError?: string;
  focusPath: number[] | null;
  onFocusPath: (path: number[] | null) => void;
  onNormaliseSlide: () => void;
  /** Remount keys for the code editors; bumped when the app changes the
   * document programmatically so the editor reloads instead of going stale. */
  slideEditorKey: string;
  cssEditorKey: string;
}

function TransitionEditor({
  value, onChange, idPrefix,
}: {
  value: SlideTransition | null;
  onChange: (t: SlideTransition | null) => void;
  idPrefix: string;
}) {
  const type: TransitionType = value?.type ?? "none";
  const duration = value?.duration_ms ?? 500;
  const DIRECTIONAL: TransitionType[] = ["push", "wipe", "cover", "uncover", "split"];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-type`}>Transition</Label>
        <Select
          value={type}
          onValueChange={(next) => {
            if (next === "none") onChange(null);
            else onChange({ type: next as SlideTransition["type"], duration_ms: duration, direction: value?.direction ?? null });
          }}
        >
          <SelectTrigger id={`${idPrefix}-type`} className="w-full">
            <SelectValue>
              {(v: string) => TRANSITION_TYPES.find((t) => t.value === v)?.label ?? v}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {TRANSITION_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {value && (
        <>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor={`${idPrefix}-duration`}>Duration</Label>
              <span className="text-xs tabular-nums text-muted-foreground">{duration} ms</span>
            </div>
            <Slider
              id={`${idPrefix}-duration`}
              min={0} max={3000} step={50} value={[duration]}
              onValueChange={(v) => { const next = Array.isArray(v) ? v[0] : v; onChange({ ...value, duration_ms: next }); }}
            />
          </div>
          {DIRECTIONAL.includes(type) && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${idPrefix}-direction`}>Direction</Label>
            <Select
              value={value.direction ?? "l"}
              onValueChange={(next) =>
                onChange({ ...value, direction: next as SlideTransition["direction"] })
              }
            >
              <SelectTrigger id={`${idPrefix}-direction`} className="w-full">
                <SelectValue>
                  {(v: string) => TRANSITION_DIRECTIONS.find((d) => d.value === v)?.label ?? v}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {TRANSITION_DIRECTIONS.map((d) => (
                  <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          )}
        </>
      )}
    </div>
  );
}

export function Inspector(p: Props) {
  const slide = p.deck.slides[p.selected];
  const preset = SIZE_PRESETS.find((s) => s.width === p.deck.width && s.height === p.deck.height);

  return (
    <Tabs defaultValue="html" className="flex h-full min-h-0 flex-col gap-0">
      <div className="shrink-0 border-b px-3 py-2">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="html">HTML</TabsTrigger>
          <TabsTrigger value="ir">IR</TabsTrigger>
          <TabsTrigger value="slide">Slide</TabsTrigger>
          <TabsTrigger value="deck">Deck</TabsTrigger>
        </TabsList>
      </div>

      <TabsContent value="html" className="flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden">
        <div className="min-h-0 flex-1 bg-background" data-html-editor="">
          {slide && (
            <CodeEditor
              key={p.slideEditorKey}
              value={slide.html}
              onChange={p.onSlideHtml}
              dark={p.dark}
              stateKey={p.slideEditorKey}
            />
          )}
        </div>
      </TabsContent>

      <TabsContent value="ir" className="flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden">
        <IrTree
          state={p.irState}
          tree={p.irResult?.tree ?? null}
          error={p.irError}
          focusPath={p.focusPath}
          onFocus={p.onFocusPath}
        />
      </TabsContent>

      <TabsContent value="slide" className="min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
        <div className="flex flex-col gap-5 p-4">
          {slide ? (
            <>
              <TransitionEditor idPrefix="slide" value={slide.transition} onChange={p.onSlideTransition} />
              <Separator />
              <div className="flex flex-col gap-2">
                <Button
                  variant="outline" size="sm" className="justify-start"
                  onClick={() =>
                    downloadText(`${slug(p.deck.name)}-slide-${p.selected + 1}.html`, slide.html)
                  }
                >
                  <FileCode2 className="h-4 w-4" /> Download this slide as HTML
                </Button>
                {isNormalisedFragment(slide.html) ? (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Native domOXML form: every element is a positioned shape, so this
                    slide parses straight to IR with no browser layout pass.
                  </p>
                ) : isForeignFragment(slide.html) ? (
                  <>
                    <Button
                      variant="outline" size="sm" className="justify-start"
                      onClick={p.onNormaliseSlide}
                    >
                      <Shapes className="h-4 w-4" /> Rebuild as native domOXML shapes
                    </Button>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      This slide is authored HTML: it needs a browser layout pass to
                      become IR. Rebuilding replaces it with the equivalent native
                      shapes, laid out identically.
                    </p>
                  </>
                ) : null}
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Slide {p.selected + 1} of {p.deck.slides.length} · {p.deck.width} × {p.deck.height}px
                </p>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No slide selected.</p>
          )}
        </div>
      </TabsContent>

      <TabsContent value="deck" className="min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
        <div className="flex flex-col gap-5 p-4">
          <div className="flex flex-col gap-1.5">
            <Label>Slide size</Label>
            <div className="grid grid-cols-2 gap-2">
              {SIZE_PRESETS.map((s) => (
                <button
                  key={s.label}
                  onClick={() => p.onDeckChange({ width: s.width, height: s.height })}
                  className={`rounded-lg border px-3 py-2 text-left transition-colors ${
                    preset?.label === s.label
                      ? "border-primary bg-accent"
                      : "border-input hover:bg-accent/60"
                  }`}
                >
                  <span className="block text-sm font-medium">{s.label}</span>
                  <span className="block text-xs text-muted-foreground">
                    {s.width} × {s.height}
                  </span>
                </button>
              ))}
            </div>
            <div className="mt-1 flex items-center gap-2">
              <Input
                type="number" min={16} max={7680} value={p.deck.width} aria-label="Width in pixels"
                onChange={(e) => p.onDeckChange({ width: Math.max(16, Number(e.target.value) || 16) })}
                className="h-8"
              />
              <span className="text-muted-foreground">×</span>
              <Input
                type="number" min={16} max={7680} value={p.deck.height} aria-label="Height in pixels"
                onChange={(e) => p.onDeckChange({ height: Math.max(16, Number(e.target.value) || 16) })}
                className="h-8"
              />
              <span className="text-xs text-muted-foreground">px</span>
            </div>
          </div>

          <Separator />

          <div className="flex flex-col gap-3">
            <Label>Set the same transition on every slide</Label>
            <DeckDefaultTransition deck={p.deck} onApply={p.onApplyTransitionToAll} />
          </div>

          <Separator />

          <div className="flex min-h-40 flex-1 flex-col gap-1.5">
            <Label>Deck stylesheet</Label>
            <div className="min-h-40 flex-1 overflow-hidden rounded-lg border">
              <CodeEditor key={p.cssEditorKey} value={p.deck.css} onChange={(css) => p.onDeckChange({ css })} dark={p.dark} language="css" stateKey={p.cssEditorKey} />
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Applied to every slide before its own markup, like a document stylesheet.
            </p>
          </div>
        </div>
      </TabsContent>
    </Tabs>
  );
}

function DeckDefaultTransition({
  deck, onApply,
}: {
  deck: Deck;
  onApply: (t: SlideTransition | null) => void;
}) {
  const [draft, setDraft] = useState<SlideTransition | null>({ type: "fade", duration_ms: 500 });
  void deck;
  return (
    <div className="flex flex-col gap-3">
      <TransitionEditor idPrefix="deck" value={draft} onChange={setDraft} />
      <Button variant="outline" size="sm" onClick={() => onApply(draft)}>
        Apply to all slides
      </Button>
    </div>
  );
}

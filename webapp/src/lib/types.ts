export type TransitionType =
  | "none" | "fade" | "push" | "wipe" | "cut"
  | "split" | "cover" | "uncover" | "zoom" | "dissolve" | "morph";

export type TransitionDirection =
  | "l" | "r" | "u" | "d" | "lu" | "ru" | "ld" | "rd" | "horz" | "vert";

export interface SlideTransition {
  type: Exclude<TransitionType, "none">;
  duration_ms?: number | null;
  direction?: TransitionDirection | null;
}

export interface Slide {
  id: string;
  html: string;
  /** null = no transition on this slide. */
  transition: SlideTransition | null;
}

export interface Deck {
  /** Identity of this deck document; replaced wholesale on open/new. */
  id: string;
  name: string;
  width: number;
  height: number;
  /** Deck-level CSS applied to every slide (the document stylesheet). */
  css: string;
  slides: Slide[];
}

export type EnginePhase =
  | "starting"      // worker created, Pyodide loading
  | "packages"      // Python packages downloading (inside loadPyodide)
  | "bundle"        // domOXML bundle unpacking
  | "ready"
  | "error";

export interface EngineStatus {
  phase: EnginePhase;
  detail?: string;
}

export interface CoverageItem {
  element: string;
  representation: string;
  editability: string;
  reason?: string;
}

export interface ConversionWarning {
  element: string;
  message: string;
}

export interface ConvertResult {
  pptx: Uint8Array;
  coverage: CoverageItem[];
  warnings: ConversionWarning[];
}

export interface ReadDeckResult {
  width: number;
  height: number;
  css: string;
  slides: { html: string; transition: SlideTransition | null }[];
}

export const TRANSITION_TYPES: { value: TransitionType; label: string }[] = [
  { value: "none", label: "None" },
  { value: "fade", label: "Fade" },
  { value: "push", label: "Push" },
  { value: "wipe", label: "Wipe" },
  { value: "cut", label: "Cut" },
  { value: "split", label: "Split" },
  { value: "cover", label: "Cover" },
  { value: "uncover", label: "Uncover" },
  { value: "zoom", label: "Zoom" },
  { value: "dissolve", label: "Dissolve" },
  { value: "morph", label: "Morph" },
];

export const TRANSITION_DIRECTIONS: { value: TransitionDirection; label: string }[] = [
  { value: "l", label: "From right" },
  { value: "r", label: "From left" },
  { value: "u", label: "From bottom" },
  { value: "d", label: "From top" },
  { value: "lu", label: "From bottom right" },
  { value: "ru", label: "From bottom left" },
  { value: "ld", label: "From top right" },
  { value: "rd", label: "From top left" },
  { value: "horz", label: "Horizontal" },
  { value: "vert", label: "Vertical" },
];

export const SIZE_PRESETS: { label: string; width: number; height: number; hint: string }[] = [
  { label: "16:9", width: 1280, height: 720, hint: "Widescreen" },
  { label: "16:9 HD", width: 1920, height: 1080, hint: "Widescreen, high resolution" },
  { label: "4:3", width: 1024, height: 768, hint: "Standard" },
  { label: "16:10", width: 1280, height: 800, hint: "Widescreen 16:10" },
];

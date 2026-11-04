import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";

interface Props {
  bitmap: ImageBitmap | null;
  url: string | null;
  alt: string;
  className?: string;
  style?: CSSProperties;
}

/** Renders a preview result: a canvas for canvas-painted bitmaps (the
 *  normal path), an <img> for engine-raster fallbacks. */
export function PreviewSurface(p: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const bitmap = p.bitmap;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !bitmap) return;
    if (canvas.width !== bitmap.width) canvas.width = bitmap.width;
    if (canvas.height !== bitmap.height) canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d");
    ctx?.drawImage(bitmap, 0, 0);
  }, [bitmap]);

  if (bitmap) {
    return (
      <canvas
        ref={canvasRef}
        className={p.className}
        style={p.style}
        role="img"
        aria-label={p.alt}
      />
    );
  }
  if (p.url) {
    return (
      <img
        src={p.url}
        alt={p.alt}
        className={p.className}
        style={p.style}
        draggable={false}
      />
    );
  }
  return null;
}

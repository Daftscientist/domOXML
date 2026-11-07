// PROTOTYPE helpers shared by the variants.
import type { Slide } from '../sample'
/** The slide's own background colour (from its root style), for ambient tints. */
export const slideColour = (s: Slide) => /background:([^;"]+)/.exec(s.html)?.[1]?.trim() ?? '#ffffff'
export const slideTitle = (s: Slide, i: number) => {
  const m = /<div data-id="e\d+"[^>]*font:700 (?:4\d|7\d)px[^>]*>([^<]+)</.exec(s.html) ?? /<div data-id="e\d+"[^>]*>([^<]{6,})</.exec(s.html)
  return m?.[1] ?? `Slide ${i + 1}`
}
export const isDark = (hex: string) => {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return false
  const n = parseInt(m[1], 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 110
}

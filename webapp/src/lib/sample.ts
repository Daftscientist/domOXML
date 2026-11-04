import type { Deck } from "./types";

let n = 0;
const id = () => `slide-${++n}-${Math.random().toString(36).slice(2, 8)}`;

export const DEFAULT_CSS = `/* Deck stylesheet: applied to every slide. */
* { box-sizing: border-box; }
body { font-family: "Geist", "Inter", system-ui, sans-serif; }
`;

/** A small, real-feeling starter deck that shows off the type scale. */
export function sampleDeck(): Deck {
  return {
    id: id(),
    name: "Product Review",
    width: 1280,
    height: 720,
    css: DEFAULT_CSS,
    slides: [
      {
        id: id(),
        transition: { type: "fade", duration_ms: 500 },
        html: `<section style="width:1280px;height:720px;background:#F2F1EA;padding:72px;display:flex;flex-direction:column;justify-content:space-between">
  <p style="font-size:15px;letter-spacing:0.18em;color:#3653C7;font-weight:600">PRODUCT REVIEW · Q3</p>
  <div>
    <h1 style="font-size:76px;line-height:1.02;color:#141414;font-weight:700;letter-spacing:-0.02em">The state of<br/>the platform</h1>
    <p style="font-size:22px;color:#4A4A45;margin-top:24px;max-width:640px;line-height:1.45">What we shipped, what it changed, and where the work goes next.</p>
  </div>
  <p style="font-size:15px;color:#8A877C">Prepared for the October review</p>
</section>`,
      },
      {
        id: id(),
        transition: { type: "push", duration_ms: 600, direction: "l" },
        html: `<section style="width:1280px;height:720px;background:#FFFFFF;padding:72px">
  <h2 style="font-size:40px;color:#141414;font-weight:700;letter-spacing:-0.01em">Three numbers that matter</h2>
  <div style="display:flex;gap:28px;margin-top:56px">
    <div style="flex:1;border-top:3px solid #3653C7;padding-top:20px">
      <p style="font-size:56px;font-weight:700;color:#141414">38</p>
      <p style="font-size:16px;color:#4A4A45;line-height:1.5;margin-top:8px">Features shipped this quarter, up from 24 in Q2.</p>
    </div>
    <div style="flex:1;border-top:3px solid #3653C7;padding-top:20px">
      <p style="font-size:56px;font-weight:700;color:#141414">99.98%</p>
      <p style="font-size:16px;color:#4A4A45;line-height:1.5;margin-top:8px">Uptime across the quarter, including two major launches.</p>
    </div>
    <div style="flex:1;border-top:3px solid #3653C7;padding-top:20px">
      <p style="font-size:56px;font-weight:700;color:#141414">1.9s</p>
      <p style="font-size:16px;color:#4A4A45;line-height:1.5;margin-top:8px">Median load time, down from 3.4s after the rendering work.</p>
    </div>
  </div>
</section>`,
      },
      {
        id: id(),
        transition: null,
        html: `<section style="width:1280px;height:720px;background:#141414;padding:72px;display:flex;flex-direction:column;justify-content:center">
  <h2 style="font-size:44px;color:#F2F1EA;font-weight:700;line-height:1.15;max-width:820px">Next quarter is about one thing: making the common path effortless.</h2>
  <p style="font-size:19px;color:#B9B6AB;margin-top:28px;max-width:640px;line-height:1.55">Everything on the roadmap either removes a step, removes a wait, or removes a decision the product can make itself.</p>
</section>`,
      },
    ],
  };
}

export function blankSlideHtml(width: number, height: number): string {
  return `<section style="width:${width}px;height:${height}px;background:#FFFFFF;padding:72px">
  <h2 style="font-size:40px;color:#141414;font-weight:700">Slide title</h2>
  <p style="font-size:19px;color:#4A4A45;line-height:1.55;margin-top:20px;max-width:640px">Write the point of this slide here. Keep it to what the audience should remember.</p>
</section>`;
}

export { id as newSlideId };

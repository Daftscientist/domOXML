// A small sample deck in domOXML's normalized HTML (absolutely positioned elements on a 1280×720 slide), used by the dev
// harness until the view is connected to the engine.
export type Slide = { id: string; html: string; notes?: string; comments?: number; hidden?: boolean }

const box = (id: string, x: number, y: number, w: number, h: number, style: string, inner = '') =>
  `<div data-id="${id}" style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;${style}">${inner}</div>`
const text = (id: string, x: number, y: number, w: number, h: number, size: number, weight: number, color: string, t: string, extra = '') =>
  box(id, x, y, w, h, `font:${weight} ${size}px/1.15 Inter, 'Helvetica Neue', Arial, sans-serif;color:${color};${extra}`, t)
const slide = (bg: string, inner: string) => `<div style="position:relative;width:1280px;height:720px;overflow:hidden;background:${bg}">${inner}</div>`

export const SAMPLE: { name: string; slides: Slide[] } = {
  name: 'Q3 review.pptx',
  slides: [
    { id: 's1', notes: 'Welcome everyone. Thirty minutes, then questions.', html: slide('#0f1b2d',
      text('e1', 96, 230, 900, 70, 26, 600, '#7aa7ff', 'QUARTERLY REVIEW', 'letter-spacing:4px') +
      text('e2', 96, 290, 1000, 180, 76, 700, '#ffffff', 'Q3 2026: steady growth, sharper focus') +
      text('e3', 96, 500, 800, 40, 24, 400, '#a9b8d0', 'Leadership team · 4 November')) },
    { id: 's2', comments: 2, html: slide('#ffffff',
      text('e4', 80, 60, 1100, 70, 44, 700, '#111827', 'What moved the number') +
      box('e5', 80, 170, 350, 420, 'background:#f3f6fb;border-radius:16px') +
      text('e6', 110, 200, 300, 60, 56, 700, '#1d4ed8', '+18%') + text('e7', 110, 270, 290, 100, 22, 400, '#374151', 'Self-serve upgrades doubled after the pricing change') +
      box('e8', 465, 170, 350, 420, 'background:#f3f6fb;border-radius:16px') +
      text('e9', 495, 200, 300, 60, 56, 700, '#1d4ed8', '1.9%') + text('e10', 495, 270, 290, 100, 22, 400, '#374151', 'Churn fell from 2.6%, best quarter on record') +
      box('e11', 850, 170, 350, 420, 'background:#f3f6fb;border-radius:16px') +
      text('e12', 880, 200, 300, 60, 56, 700, '#1d4ed8', '2') + text('e13', 880, 270, 290, 100, 22, 400, '#374151', 'Enterprise pilots converted a quarter early')) },
    { id: 's3', html: slide('#ffffff',
      text('e14', 80, 60, 1100, 70, 44, 700, '#111827', 'Revenue by quarter') +
      [['Q1', 260], ['Q2', 300], ['Q3', 380], ['Q4', 340]].map(([q, h], i) =>
        box(`e${15 + i}`, 160 + i * 250, 640 - (h as number), 150, h as number, `background:${i === 2 ? '#1d4ed8' : '#93c5fd'};border-radius:8px 8px 0 0`) +
        text(`e${20 + i}`, 160 + i * 250, 650, 150, 40, 22, 600, '#374151', q as string, 'text-align:center')).join('')) },
    { id: 's4', html: slide('#f7f4ee',
      text('e24', 80, 70, 1100, 70, 44, 700, '#1f2937', 'Next quarter') +
      ['Ship usage-based pricing to all plans', 'Hire two enterprise AEs', 'Launch the partner programme'].map((t, i) =>
        box(`e${25 + i}`, 80, 190 + i * 110, 52, 52, 'background:#1f2937;border-radius:999px;color:#fff;font:700 24px/52px Inter,Arial;text-align:center', String(i + 1)) +
        text(`e${30 + i}`, 160, 196 + i * 110, 1000, 50, 32, 500, '#1f2937', t)).join('')) },
    { id: 's5', hidden: true, html: slide('#ffffff', text('e40', 80, 300, 1100, 80, 40, 600, '#9ca3af', 'Appendix: detailed numbers')) },
    { id: 's6', html: slide('#0f1b2d', text('e41', 96, 300, 1000, 100, 72, 700, '#ffffff', 'Questions')) },
  ],
}

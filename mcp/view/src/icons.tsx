// Small stroke icons (1.6px, currentColor), so they take the host's text colour and weight.
const P: Record<string, string> = {
  deck: 'M4 5h16v11H4z M9 20h6 M12 16v4',
  play: 'M8 5.5v13l10-6.5z',
  download: 'M12 4v11 M7 10l5 5 5-5 M5 19h14',
  expand: 'M14 4h6v6 M10 20H4v-6 M20 4l-7 7 M4 20l7-7',
  collapse: 'M20 10h-6V4 M4 14h6v6 M14 10l7-7 M10 14l-7 7',
  undo: 'M9 7L4 12l5 5 M4 12h11a5 5 0 0 1 0 10h-2',
  redo: 'M15 7l5 5-5 5 M20 12H9a5 5 0 0 0 0 10h2',
  comment: 'M5 5h14v10H9l-4 4z',
  plus: 'M12 5v14 M5 12h14',
  caret: 'M7 10l5 5 5-5',
  more: 'M6 12h.01 M12 12h.01 M18 12h.01',
  up: 'M7 14l5-5 5 5',
  down: 'M7 10l5 5 5-5',
  left: 'M15 6l-6 6 6 6',
  right: 'M9 6l6 6-6 6',
  text: 'M5 6h14 M12 6v13',
  shape: 'M4 4h9v9H4z M15.5 11a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9z',
  image: 'M4 5h16v14H4z M4 16l5-5 4 4 3-3 4 4 M15 9h.01',
  table: 'M4 5h16v14H4z M4 10h16 M4 15h16 M10 5v14',
  chart: 'M5 19V9 M10 19V5 M15 19v-7 M20 19v-4',
  sparkle: 'M12 4l1.8 4.6L18 10l-4.2 1.4L12 16l-1.8-4.6L6 10l4.2-1.4z',
  check: 'M5 12l5 5L19 7',
  x: 'M6 6l12 12 M18 6L6 18',
}

export function Icon({ name, small }: { name: keyof typeof P | string; small?: boolean }) {
  const s = small ? 12 : 16
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill={name === 'play' ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={name === 'more' ? 3 : 1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={P[name] ?? ''} />
    </svg>
  )
}

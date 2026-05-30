"""Compose a single slide into a full, fixed-size HTML document for rendering."""

from __future__ import annotations

from domoxml.types import Theme

_RESET = "*{margin:0;padding:0;box-sizing:border-box}"


def compile_theme(theme: Theme) -> str:
    """Compile a :class:`~domoxml.types.Theme` into ``:root`` CSS custom properties."""
    palette = theme.palette
    fonts = theme.fonts
    return (
        ":root{"
        f"--background:{palette.background};"
        f"--foreground:{palette.foreground};"
        f"--accent:{palette.accent};"
        f"--muted:{palette.muted};"
        f"--font-heading:{fonts.heading};"
        f"--font-body:{fonts.body};"
        "}"
    )


def compose_page(
    slide_html: str,
    *,
    css: str | None,
    theme: Theme,
    width_px: int,
    height_px: int,
) -> str:
    """Wrap a slide fragment in a complete HTML page sized to the slide.

    The body is locked to exactly ``width_px`` x ``height_px`` with hidden overflow, so a
    full-page screenshot is the slide and nothing else.
    """
    frame = (
        f"html,body{{width:{width_px}px;height:{height_px}px;overflow:hidden;"
        "background:var(--background);color:var(--foreground);"
        "font-family:var(--font-body),sans-serif}"
    )
    style = f"{_RESET}{compile_theme(theme)}{frame}{css or ''}"
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{style}</style></head><body>{slide_html}</body></html>"
    )

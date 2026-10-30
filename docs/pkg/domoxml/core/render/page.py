"""Compose a single slide into a full, fixed-size HTML document for rendering."""

from __future__ import annotations

from domoxml.types import Theme

_RESET = "*{margin:0;padding:0;box-sizing:border-box}"
_CSS_STRUCTURAL = str.maketrans("", "", ";{}\n\r")


def _css_value(value: str, fallback: str) -> str:
    """Strip CSS-structural characters so a theme token can't break the ``:root`` block.

    Not a security boundary — the raw ``css`` argument is passed through verbatim — just a
    guard against a stray ``;``/``}``/newline in a token silently corrupting the stylesheet.
    """
    return value.translate(_CSS_STRUCTURAL).strip() or fallback


def compile_theme(theme: Theme) -> str:
    """Compile a :class:`~domoxml.types.Theme` into ``:root`` CSS custom properties."""
    palette = theme.palette
    fonts = theme.fonts
    return (
        ":root{"
        f"--background:{_css_value(palette.background, '#ffffff')};"
        f"--foreground:{_css_value(palette.foreground, '#000000')};"
        f"--accent:{_css_value(palette.accent, '#4f46e5')};"
        f"--muted:{_css_value(palette.muted, '#6b7280')};"
        f"--font-heading:{_css_value(fonts.heading, 'sans-serif')};"
        f"--font-body:{_css_value(fonts.body, 'sans-serif')};"
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
    if width_px <= 0 or height_px <= 0:
        raise ValueError(
            f"compose_page: width_px and height_px must be positive, got {width_px}x{height_px}"
        )
    frame = (
        f"html,body{{width:{width_px}px;height:{height_px}px;overflow:hidden;"
        "background:var(--background);color:var(--foreground);"
        "font-family:var(--font-body),sans-serif}"
    )
    framework = f"{_RESET}{compile_theme(theme)}{frame}"
    # User CSS goes in its own <style> so a leading `@import` (e.g. a web-font stylesheet) is
    # valid — `@import` must precede all other rules in *its* stylesheet, not the framework's.
    user_style = f"<style>{css}</style>" if css else ""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{framework}</style>{user_style}</head><body>{slide_html}</body></html>"
    )

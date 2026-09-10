"""Shared visual system for the generated profile assets.

Defines the two palettes (light and dark), the SVG-safe font stack and a
handful of element helpers used by the hand-written SVG generators. Every
colour used by any generator originates here: nothing downstream hard-codes
a hex value.

Pure module. No I/O, no network, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from xml.sax.saxutils import escape

# The single accent of the whole profile. It is the link colour from the
# LaTeX CV, so the profile and the CV read as one set of materials.
ACCENT_LIGHT = "#0B5394"
ACCENT_DARK = "#6BA8E5"

# No webfonts: GitHub's image proxy will not fetch them and the text would
# fall back unpredictably. System stack only.
FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif'


@dataclass(frozen=True)
class Theme:
    """A resolved colour scheme for one of the two GitHub themes."""

    name: str
    accent: str
    text: str
    muted: str
    empty: str
    grid: str
    ramp_far: str

    @property
    def suffix(self) -> str:
        """Filename suffix for assets rendered in this theme."""
        return self.name


LIGHT = Theme(
    name="light",
    accent=ACCENT_LIGHT,
    text="#1F2328",
    muted="#59636E",
    empty="#EBEDF0",
    grid="#D1D9E0",
    # Far end of the categorical ramp. Chosen to stay clearly visible against
    # the page behind it, so no series fades into the background.
    ramp_far="#94B3D1",
)

DARK = Theme(
    name="dark",
    accent=ACCENT_DARK,
    text="#E6EDF3",
    muted="#8B949E",
    empty="#21262D",
    grid="#30363D",
    # On a dark page the ramp runs lighter, not darker, for the same reason.
    ramp_far="#CFE2F7",
)

THEMES: tuple[Theme, ...] = (LIGHT, DARK)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Convert ``#RRGGBB`` to an integer RGB triple."""
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected a #RRGGBB colour, got {value!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """Convert an integer RGB triple back to ``#RRGGBB``."""
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def mix(start: str, end: str, ratio: float) -> str:
    """Linearly interpolate between two hex colours.

    ``ratio`` of 0.0 returns ``start``, 1.0 returns ``end``.
    """
    ratio = max(0.0, min(1.0, ratio))
    a = _hex_to_rgb(start)
    b = _hex_to_rgb(end)
    return _rgb_to_hex(tuple(round(x + (y - x) * ratio) for x, y in zip(a, b)))  # type: ignore[arg-type]


def heat_scale(theme: Theme, steps: int = 5) -> list[str]:
    """Contribution-cell colours, from the empty cell to the full accent.

    Index 0 is the empty cell; the remaining ``steps - 1`` entries are
    evenly spaced towards the accent, matching the five intensity levels
    GitHub's own calendar uses.
    """
    if steps < 2:
        raise ValueError("heat_scale needs at least two steps")
    scale = [theme.empty]
    for i in range(1, steps):
        # Start at a visible tint rather than at the empty colour itself,
        # so level 1 is distinguishable from a blank day.
        ratio = 0.25 + 0.75 * (i - 1) / (steps - 2) if steps > 2 else 1.0
        scale.append(mix(theme.empty, theme.accent, ratio))
    return scale


def series_colors(theme: Theme, count: int) -> list[str]:
    """A monochrome ramp of ``count`` distinguishable shades of the accent.

    Used for stacked bars and legends, where a second hue would break the
    one-accent rule. Runs from the full accent to ``ramp_far``, which sits on
    the contrasting side of the page in both themes so that no series ends up
    the same value as the background behind it.
    """
    if count < 1:
        return []
    if count == 1:
        return [theme.accent]
    return [mix(theme.accent, theme.ramp_far, i / (count - 1)) for i in range(count)]


def svg_open(width: float, height: float, title: str) -> str:
    """Opening ``<svg>`` tag with a transparent background and an a11y title.

    The background is deliberately not filled: GitHub supplies the page
    colour, and a baked-in fill reads as a pasted rectangle in whichever
    theme it does not match.
    """
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(width)}" '
        f'height="{fmt(height)}" viewBox="0 0 {fmt(width)} {fmt(height)}" '
        f'role="img" aria-label="{escape(title)}" font-family=\'{FONT_STACK}\'>'
        f"<title>{escape(title)}</title>"
    )


def svg_close() -> str:
    """Closing ``</svg>`` tag."""
    return "</svg>"


def rect(
    x: float,
    y: float,
    width: float,
    height: float,
    fill: str,
    radius: float = 0.0,
) -> str:
    """A filled rectangle, optionally with rounded corners."""
    r = f' rx="{fmt(radius)}" ry="{fmt(radius)}"' if radius else ""
    return (
        f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(width)}" '
        f'height="{fmt(height)}" fill="{fill}"{r}/>'
    )


def text(
    x: float,
    y: float,
    content: str,
    fill: str,
    size: float = 11.0,
    weight: str = "normal",
    anchor: str = "start",
) -> str:
    """A single line of text in the shared font stack."""
    return (
        f'<text x="{fmt(x)}" y="{fmt(y)}" fill="{fill}" font-size="{fmt(size)}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{escape(content)}</text>'
    )


def fmt(value: float) -> str:
    """Format a number for SVG output without trailing zeros."""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def join(parts: Iterable[str]) -> str:
    """Concatenate SVG fragments into a single document body."""
    return "".join(parts)

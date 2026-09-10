"""Generate the language-share SVGs.

Aggregates language byte counts across the profile owner's public, non-fork
repositories, keeps the eight largest and folds the remainder into "Other",
then renders a horizontal stacked bar with a labelled legend, in both theme
variants.

Shares are reported exactly as GitHub measures them -- by bytes of source
checked in -- and are not rebalanced.

Writes:
    assets/lang-stats-light.svg
    assets/lang-stats-dark.svg

Run standalone:
    python scripts/gen_lang_stats.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_api  # noqa: E402
import theme as th  # noqa: E402

LOGGER = logging.getLogger("gen_lang_stats")

TOP_N = 8
OTHER_LABEL = "Other"

WIDTH = 723.0
BAR_HEIGHT = 20.0
BAR_RADIUS = 4.0
LEGEND_TOP_GAP = 16.0
LEGEND_ROW_HEIGHT = 20.0
LEGEND_COLUMNS = 3
SWATCH = 10.0


def top_shares(totals: dict[str, int], top_n: int = TOP_N) -> list[tuple[str, float]]:
    """Return (language, share) pairs for the top ``top_n``, plus "Other".

    Shares are fractions of the total byte count and sum to 1.0.
    """
    if not totals:
        raise ValueError("no language totals to summarise")

    grand_total = sum(totals.values())
    if grand_total <= 0:
        raise ValueError("language totals sum to zero")

    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    head = ranked[:top_n]
    tail = ranked[top_n:]

    shares = [(name, size / grand_total) for name, size in head]
    if tail:
        shares.append((OTHER_LABEL, sum(size for _name, size in tail) / grand_total))
    return shares


def _format_share(share: float) -> str:
    """Format a fractional share as a percentage string."""
    percent = share * 100
    if 0 < percent < 0.1:
        return "<0.1%"
    return f"{percent:.1f}%"


def render(shares: list[tuple[str, float]], palette: th.Theme) -> str:
    """Render one theme variant of the language-share chart as SVG."""
    if not shares:
        raise ValueError("no shares to render")

    colours = th.series_colors(palette, len(shares))
    rows = -(-len(shares) // LEGEND_COLUMNS)  # ceiling division
    height = BAR_HEIGHT + LEGEND_TOP_GAP + rows * LEGEND_ROW_HEIGHT

    label = "Language share across public repositories, by bytes of code"
    parts: list[str] = [th.svg_open(WIDTH, height, label)]

    # Rounded outer corners on the bar as a whole, square joins between the
    # segments inside it.
    parts.append(
        f'<defs><clipPath id="bar-clip"><rect x="0" y="0" width="{th.fmt(WIDTH)}" '
        f'height="{th.fmt(BAR_HEIGHT)}" rx="{th.fmt(BAR_RADIUS)}" ry="{th.fmt(BAR_RADIUS)}"/>'
        f"</clipPath></defs>"
    )
    parts.append('<g clip-path="url(#bar-clip)">')
    # An empty-colour base means rounding errors show as background, not as gaps.
    parts.append(th.rect(0, 0, WIDTH, BAR_HEIGHT, palette.empty))

    offset = 0.0
    for (name, share), colour in zip(shares, colours):
        segment = share * WIDTH
        if segment <= 0:
            continue
        # Overdraw slightly so adjacent segments never leave a seam.
        parts.append(th.rect(offset, 0, segment + 0.5, BAR_HEIGHT, colour))
        LOGGER.debug("%s: %.4f -> %.2fpx", name, share, segment)
        offset += segment
    parts.append("</g>")

    column_width = WIDTH / LEGEND_COLUMNS
    for index, ((name, share), colour) in enumerate(zip(shares, colours)):
        column = index % LEGEND_COLUMNS
        row = index // LEGEND_COLUMNS
        x = column * column_width
        y = BAR_HEIGHT + LEGEND_TOP_GAP + row * LEGEND_ROW_HEIGHT
        parts.append(th.rect(x, y - SWATCH + 1, SWATCH, SWATCH, colour, radius=2))
        parts.append(
            th.text(x + SWATCH + 7, y, f"{name} {_format_share(share)}", palette.text, size=11)
        )

    parts.append(th.svg_close())
    return th.join(parts)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets",
        help="directory to write the SVG variants into (default: assets/)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        auth = github_api.resolve_auth()
        language_totals = github_api.fetch_language_bytes(auth)
    except github_api.GitHubError as exc:
        LOGGER.error("could not fetch language data: %s", exc)
        return 1

    if language_totals.partial:
        LOGGER.warning(
            "language data is partial (%d repositories counted): %s",
            language_totals.repos_counted,
            language_totals.partial_reason,
        )

    try:
        shares = top_shares(language_totals.totals)
    except ValueError as exc:
        LOGGER.error("could not summarise language data: %s", exc)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for palette in th.THEMES:
        svg = render(shares, palette)
        path = args.out_dir / f"lang-stats-{palette.suffix}.svg"
        path.write_text(svg, encoding="utf-8")
        LOGGER.info("wrote %s (%d bytes)", path, len(svg))

    LOGGER.info(
        "top language: %s at %s over %d repositories",
        shares[0][0],
        _format_share(shares[0][1]),
        language_totals.repos_counted,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

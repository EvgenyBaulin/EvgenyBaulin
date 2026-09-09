"""Generate the contribution heatmap SVGs.

Renders a GitHub-style 53x7 contribution calendar with month labels, in both
theme variants, from the data returned by ``github_api.fetch_contributions``.

Writes:
    assets/contrib-heatmap-light.svg
    assets/contrib-heatmap-dark.svg

Run standalone:
    python scripts/gen_contrib_heatmap.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_api  # noqa: E402
import theme as th  # noqa: E402

LOGGER = logging.getLogger("gen_contrib_heatmap")

CELL = 11.0
GAP = 2.0
PITCH = CELL + GAP
RADIUS = 2.0
MARGIN_LEFT = 30.0
MARGIN_TOP = 22.0
FOOTER = 30.0
WEEKDAY_LABELS = {1: "Mon", 3: "Wed", 5: "Fri"}
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _parse_day(raw: dict[str, Any]) -> tuple[date, int | None, int]:
    """Split a raw day record into (date, count, level)."""
    day = datetime.strptime(raw["date"], "%Y-%m-%d").date()
    count = raw.get("count")
    level = int(raw.get("level") or 0)
    return day, count, level


def _column_of(day: date, first: date) -> int:
    """Grid column for a day, counting weeks from the Sunday on or before ``first``."""
    # Python weekday(): Monday=0 .. Sunday=6. GitHub's calendar starts on Sunday.
    first_sunday = first.toordinal() - ((first.weekday() + 1) % 7)
    return (day.toordinal() - first_sunday) // 7


def _row_of(day: date) -> int:
    """Grid row for a day, with Sunday at the top."""
    return (day.weekday() + 1) % 7


def render(calendar: github_api.ContributionCalendar, palette: th.Theme) -> str:
    """Render one theme variant of the contribution calendar as SVG."""
    days = [_parse_day(d) for d in calendar.days]
    if not days:
        raise ValueError("no contribution days to render")

    days.sort(key=lambda item: item[0])
    first_day = days[0][0]
    columns = _column_of(days[-1][0], first_day) + 1
    scale = th.heat_scale(palette)

    width = MARGIN_LEFT + columns * PITCH + 4
    height = MARGIN_TOP + 7 * PITCH + FOOTER
    parts: list[str] = []

    caption = "Contribution activity over the past year"
    parts.append(th.svg_open(width, height, caption))

    # Month labels, printed once per month at the column where it first appears.
    seen_months: set[tuple[int, int]] = set()
    for day, _count, _level in days:
        key = (day.year, day.month)
        if key in seen_months:
            continue
        seen_months.add(key)
        column = _column_of(day, first_day)
        if column >= columns - 1:
            continue
        parts.append(
            th.text(
                MARGIN_LEFT + column * PITCH,
                MARGIN_TOP - 8,
                MONTH_NAMES[day.month - 1],
                palette.muted,
                size=10,
            )
        )

    # Weekday labels down the left edge.
    for row, label in WEEKDAY_LABELS.items():
        parts.append(
            th.text(
                MARGIN_LEFT - 6,
                MARGIN_TOP + row * PITCH + CELL - 1.5,
                label,
                palette.muted,
                size=9,
                anchor="end",
            )
        )

    # Day cells.
    for day, _count, level in days:
        column = _column_of(day, first_day)
        row = _row_of(day)
        parts.append(
            th.rect(
                MARGIN_LEFT + column * PITCH,
                MARGIN_TOP + row * PITCH,
                CELL,
                CELL,
                scale[min(level, len(scale) - 1)],
                radius=RADIUS,
            )
        )

    footer_y = MARGIN_TOP + 7 * PITCH + 16

    # A total is printed only when exact counts were actually available.
    if calendar.counts_available and calendar.total is not None:
        noun = "contribution" if calendar.total == 1 else "contributions"
        parts.append(
            th.text(MARGIN_LEFT, footer_y, f"{calendar.total:,} {noun} in the last year", palette.muted, size=10)
        )
    else:
        LOGGER.warning("exact counts unavailable; omitting the total caption")

    # Intensity legend, right-aligned.
    legend_width = 5 * PITCH
    legend_x = width - legend_width - 34
    parts.append(th.text(legend_x - 5, footer_y, "Less", palette.muted, size=10, anchor="end"))
    for index, colour in enumerate(scale):
        parts.append(
            th.rect(legend_x + index * PITCH, footer_y - CELL + 2.5, CELL, CELL, colour, radius=RADIUS)
        )
    parts.append(th.text(legend_x + legend_width + 3, footer_y, "More", palette.muted, size=10))

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
        calendar = github_api.fetch_contributions(auth)
    except github_api.GitHubError as exc:
        LOGGER.error("could not fetch contribution data: %s", exc)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for palette in th.THEMES:
        try:
            svg = render(calendar, palette)
        except ValueError as exc:
            LOGGER.error("could not render the %s variant: %s", palette.name, exc)
            return 1
        path = args.out_dir / f"contrib-heatmap-{palette.suffix}.svg"
        path.write_text(svg, encoding="utf-8")
        LOGGER.info("wrote %s (%d bytes)", path, len(svg))

    if not calendar.counts_available:
        LOGGER.warning("rendered from intensity levels only (source: %s)", calendar.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

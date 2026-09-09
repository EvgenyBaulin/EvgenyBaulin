"""Generate the reinforcement-learning result chart.

Plots mean expected profit per evaluation run for each of the six RL agents
across the six market scenarios, with 95% confidence intervals, in both theme
variants.

Source data is ``data/rl_scenario_summary.csv``, exported by the thesis
simulator (Evaluation-of-RL-framework-in-a-credit-scoring-problem,
rl-credit-scoring-sim/artifacts/tables/main_scenario_summary.csv). Every value
plotted is read from that file; nothing is synthesised.

Writes:
    assets/rl-thresholds-light.svg
    assets/rl-thresholds-dark.svg

Run standalone:
    python scripts/gen_rl_chart.py
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import theme as th  # noqa: E402

LOGGER = logging.getLogger("gen_rl_chart")

DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "data" / "rl_scenario_summary.csv"

# The six learning agents, in the order they are introduced in the thesis.
# Baselines in the same file are deliberately excluded: the chart is capped at
# six series so it stays legible at profile width.
AGENTS: tuple[tuple[str, str], ...] = (
    ("dqn", "DQN"),
    ("double_dqn", "Double DQN"),
    ("a2c", "A2C"),
    ("a3c", "A3C"),
    ("ppo", "PPO"),
    ("sac", "SAC"),
)

SCENARIO_LABELS: dict[str, str] = {
    "base_market": "Base\nmarket",
    "adverse_stress": "Adverse\nstress",
    "drift": "Drift",
    "noise": "Noise",
    "class_imbalance_shift": "Class\nimbalance",
    "split_policy_dynamics": "Split-policy\ndynamics",
}

SCENARIO_ORDER: tuple[str, ...] = (
    "base_market",
    "adverse_stress",
    "drift",
    "noise",
    "class_imbalance_shift",
    "split_policy_dynamics",
)

# Values in the source file are absolute monetary units; the axis reports
# thousands so the tick labels stay short.
SCALE = 1_000.0

FONT_CANDIDATES = ["Helvetica", "Helvetica Neue", "Arial", "Segoe UI", "DejaVu Sans"]


class MissingData(RuntimeError):
    """Raised when the source file is absent or does not contain what is needed."""


def load_rows(source: Path) -> dict[tuple[str, str], tuple[float, float, float]]:
    """Read (agent, scenario) -> (mean, ci_lower, ci_upper) from the summary CSV."""
    if not source.exists():
        raise MissingData(
            f"{source} not found. See 'Adding the research chart' in SETUP.md."
        )

    required = {
        "controller",
        "scenario_name",
        "expected_profit_mean",
        "expected_profit_ci_lower",
        "expected_profit_ci_upper",
    }

    table: dict[tuple[str, str], tuple[float, float, float]] = {}
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise MissingData(f"{source} is missing columns: {sorted(missing)}")

        for row in reader:
            key = (row["controller"], row["scenario_name"])
            try:
                table[key] = (
                    float(row["expected_profit_mean"]),
                    float(row["expected_profit_ci_lower"]),
                    float(row["expected_profit_ci_upper"]),
                )
            except (TypeError, ValueError):
                LOGGER.warning("skipping unparseable row for %s", key)

    if not table:
        raise MissingData(f"{source} contains no usable rows")
    return table


def render(
    table: dict[tuple[str, str], tuple[float, float, float]],
    palette: th.Theme,
    out_path: Path,
) -> None:
    """Render one theme variant of the grouped bar chart to ``out_path``."""
    scenarios = [s for s in SCENARIO_ORDER if any((a, s) in table for a, _ in AGENTS)]
    if not scenarios:
        raise MissingData("none of the expected scenarios are present in the source data")

    colours = th.series_colors(palette, len(AGENTS))
    group_width = 0.82
    bar_width = group_width / len(AGENTS)

    with plt.rc_context(
        {
            "font.family": "sans-serif",
            "font.sans-serif": FONT_CANDIDATES,
            "svg.fonttype": "none",
            "text.color": palette.text,
            "axes.labelcolor": palette.text,
            "xtick.color": palette.muted,
            "ytick.color": palette.muted,
            "axes.edgecolor": palette.grid,
            "grid.color": palette.grid,
        }
    ):
        figure, axes = plt.subplots(figsize=(9.0, 3.9))
        figure.patch.set_alpha(0.0)
        axes.patch.set_alpha(0.0)

        for index, ((key, label), colour) in enumerate(zip(AGENTS, colours)):
            positions, heights, lower, upper = [], [], [], []
            for slot, scenario in enumerate(scenarios):
                entry = table.get((key, scenario))
                if entry is None:
                    LOGGER.warning("no data for %s in %s", label, scenario)
                    continue
                mean, ci_low, ci_high = entry
                positions.append(slot - group_width / 2 + bar_width * (index + 0.5))
                heights.append(mean / SCALE)
                lower.append(max(0.0, (mean - ci_low) / SCALE))
                upper.append(max(0.0, (ci_high - mean) / SCALE))

            axes.bar(
                positions,
                heights,
                width=bar_width * 0.92,
                label=label,
                color=colour,
                linewidth=0,
                yerr=[lower, upper],
                error_kw={"ecolor": palette.muted, "elinewidth": 0.7, "capsize": 1.5, "capthick": 0.7},
            )

        axes.set_xticks(range(len(scenarios)))
        axes.set_xticklabels([SCENARIO_LABELS.get(s, s) for s in scenarios], fontsize=9)
        axes.set_xlabel("Market scenario", fontsize=10, labelpad=8)
        axes.set_ylabel("Expected profit per evaluation run,\nthousands of monetary units", fontsize=10)
        axes.tick_params(axis="y", labelsize=9)
        axes.set_axisbelow(True)
        axes.yaxis.grid(True, linewidth=0.6, alpha=0.55)
        axes.xaxis.grid(False)
        for side in ("top", "right"):
            axes.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            axes.spines[side].set_linewidth(0.7)

        legend = axes.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, 1.16),
            ncol=len(AGENTS),
            frameon=False,
            fontsize=9,
            handlelength=1.1,
            handleheight=1.1,
            columnspacing=1.4,
            handletextpad=0.5,
        )
        for text_item in legend.get_texts():
            text_item.set_color(palette.text)

        # No title: the README paragraph above the image supplies the context.
        figure.tight_layout()
        figure.savefig(out_path, format="svg", transparent=True, bbox_inches="tight", pad_inches=0.06)
        plt.close(figure)

    LOGGER.info("wrote %s", out_path)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets",
        help="directory to write the SVG variants into (default: assets/)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"result table to plot (default: {DEFAULT_SOURCE.name})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        table = load_rows(args.source)
    except MissingData as exc:
        LOGGER.error("%s", exc)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for palette in th.THEMES:
        try:
            render(table, palette, args.out_dir / f"rl-thresholds-{palette.suffix}.svg")
        except MissingData as exc:
            LOGGER.error("could not render the %s variant: %s", palette.name, exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

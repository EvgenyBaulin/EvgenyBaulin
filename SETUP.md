# Setup

This repository generates the images used by `README.md` instead of embedding
third-party widgets. Everything under `assets/` is produced by the scripts in
`scripts/` and committed, so the profile renders even when an external service
is down or rate-limiting.

Read this top to bottom the first time. After that, the only sections you are
likely to need again are [Previewing](#4-previewing-the-readme) and
[Troubleshooting](#6-troubleshooting).

- [1. Creating `PROFILE_TOKEN`](#1-creating-profile_token)
- [2. Local environment](#2-local-environment)
- [3. Running the generators](#3-running-the-generators)
- [4. Previewing the README](#4-previewing-the-readme)
- [5. Changing the accent colour](#5-changing-the-accent-colour)
- [6. Troubleshooting](#6-troubleshooting)

---

## 1. Creating `PROFILE_TOKEN`

The generators work without a token, but the unauthenticated path is limited
(see [Troubleshooting](#6-troubleshooting)). A token raises the REST quota from
60 to 5,000 requests per hour and enables the GraphQL contributions query,
which returns exact daily counts.

### Generate the token

1. Open <https://github.com/settings/tokens>. You can also reach it from any
   page: click your avatar (top right) → **Settings** → **Developer settings**
   (bottom of the left sidebar) → **Personal access tokens** → **Tokens
   (classic)**.
2. Click **Generate new token** → **Generate new token (classic)**.
3. Fill in the form:
   - **Note**: `profile-readme-assets`
   - **Expiration**: 90 days is a reasonable default. GitHub emails you before
     it lapses; when it does, repeat this section and update the secret.
4. Under **Select scopes**, tick exactly two boxes:
   - **`public_repo`** — nested under the top-level **`repo`** heading. Tick
     `public_repo` itself, **not** the parent `repo` checkbox, which would
     grant private repository access the generators do not need.
   - **`read:user`** — nested under the top-level **`user`** heading.
5. Click **Generate token** at the bottom of the page.
6. Copy the token now. GitHub shows it exactly once.

### Add it as a repository secret

1. Go to this repository → **Settings** tab → in the left sidebar,
   **Secrets and variables** → **Actions**.
2. Stay on the **Secrets** tab and click **New repository secret**.
3. **Name**: `PROFILE_TOKEN`. **Secret**: paste the token.
4. Click **Add secret**.

The scheduled workflow reads it from the secret store and passes it as an
environment variable. It is never printed to the logs.

### Using it locally

Export it in your shell rather than writing it into a file:

```sh
export PROFILE_TOKEN=ghp_yourtokenhere
```

The scripts also accept `GITHUB_TOKEN` as a fallback. Never commit either one.

---

## 2. Local environment

Python 3.11 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`.venv/` is gitignored.

---

## 3. Running the generators

Each script runs standalone and writes both theme variants. All of them accept
`--out-dir` (default `assets/`) and `-v` for debug logging.

```sh
python scripts/gen_contrib_heatmap.py
python scripts/gen_lang_stats.py
python scripts/gen_rl_chart.py
```

| Script | Writes | Source |
| --- | --- | --- |
| `gen_contrib_heatmap.py` | `assets/contrib-heatmap-light.svg`, `assets/contrib-heatmap-dark.svg` | GitHub contributions calendar |
| `gen_lang_stats.py` | `assets/lang-stats-light.svg`, `assets/lang-stats-dark.svg` | GitHub REST `/languages` per public repository |
| `gen_rl_chart.py` | `assets/rl-thresholds-light.svg`, `assets/rl-thresholds-dark.svg` | `data/rl_scenario_summary.csv` (committed) |

`scripts/theme.py` holds the palette and SVG helpers; it has no entry point.
`scripts/github_api.py` is the shared API client and is likewise not run
directly.

API responses are cached as JSON under `data/` and reused while they are less
than six hours old, so repeated local runs do not burn rate limit. To force a
fresh fetch, delete the cache:

```sh
rm -f data/contributions.json data/languages.json
```

### The research chart's data

`gen_rl_chart.py` reads `data/rl_scenario_summary.csv`, exported from the
thesis simulator
([Evaluation-of-RL-framework-in-a-credit-scoring-problem](https://github.com/EvgenyBaulin/Evaluation-of-RL-framework-in-a-credit-scoring-problem),
`rl-credit-scoring-sim/artifacts/tables/main_scenario_summary.csv`). It needs
these columns:

| Column | Meaning |
| --- | --- |
| `controller` | Agent or baseline identifier, e.g. `ppo`, `double_dqn` |
| `scenario_name` | Market scenario, e.g. `base_market`, `adverse_stress` |
| `expected_profit_mean` | Mean expected profit per evaluation run |
| `expected_profit_ci_lower` | Lower bound of the 95% confidence interval |
| `expected_profit_ci_upper` | Upper bound of the 95% confidence interval |

Other columns are ignored. To plot a newer export, drop it in and point the
script at it:

```sh
python scripts/gen_rl_chart.py --source data/your-export.csv
```

The agents plotted and the scenario order are the `AGENTS` and
`SCENARIO_ORDER` constants at the top of the script. The chart is capped at
six series so it stays legible at profile width; baselines present in the same
file are deliberately not plotted.

---

## 4. Previewing the README

`preview.html` renders `README.md` roughly as GitHub does, so you can check
spacing and image sizing without pushing.

It fetches `README.md` over HTTP, and `fetch()` refuses `file://` URLs, so it
must be served:

```sh
python -m http.server 8000
```

Then open <http://localhost:8000/preview.html>.

The **Switch to dark** / **Switch to light** button in the top right flips the
page palette and swaps every generated SVG to its matching variant. Use it to
check both variants — the `<picture>` media queries in the README follow your
operating system's real colour scheme, which the button cannot change, so this
is the only way to see both without changing your system settings.

---

## 5. Changing the accent colour

The accent is defined once, in `scripts/theme.py`:

```python
ACCENT_LIGHT = "#0B5394"
ACCENT_DARK  = "#6BA8E5"
```

It is the link colour from the LaTeX CV, so the profile and the CV read as one
set of materials. Change those two constants and re-run all three generators;
every SVG picks it up.

Two things do not come from `theme.py` and need editing by hand if you change
the accent:

- `ramp_far` on each `Theme` in `scripts/theme.py` — the far end of the
  multi-series ramp. It must stay clearly visible against the page behind it:
  light on a dark background, dark on a light one.
- The five `img.shields.io/badge/...-0B5394?style=flat` URLs in `README.md`.

---

## 6. Troubleshooting

### "GitHub rate limit reached"

```
ERROR github_api: could not fetch language data: GitHub rate limit reached for
https://api.github.com/repos/... Set PROFILE_TOKEN to raise the quota.
```

Unauthenticated REST allows 60 requests per hour, and the language generator
uses one request per public repository plus one to list them. Either export
`PROFILE_TOKEN` (see [section 1](#1-creating-profile_token)) or wait for the
hour to roll over. The client does not retry against an exhausted quota; if it
hits the cap partway through it keeps whatever it already retrieved and logs
that the data is partial.

### No token found

```
WARNING github_api: auth tier 3: no token found; falling back to the public
contributions fragment. Exact contribution counts may be unavailable.
```

This is a warning, not an error — the generators continue. Credentials are
resolved in three tiers: `PROFILE_TOKEN`, then `GITHUB_TOKEN`, then no token
at all.

### What the unauthenticated fallback degrades to

Without a token the heatmap is built from the public contributions fragment at
`https://github.com/users/EvgenyBaulin/contributions` rather than from
GraphQL. That page reliably exposes each day's date and intensity level;
exact counts appear only in tooltip text, and that markup changes from time to
time. When the counts cannot be recovered the grid still renders from the
intensity levels, and the total-contributions caption is omitted rather than
guessed. You will see:

```
WARNING gen_contrib_heatmap: exact counts unavailable; omitting the total caption
```

Setting `PROFILE_TOKEN` restores exact counts and the caption.

If the fragment's markup changes enough that no day cells are found at all,
the generator fails with `could not find any day cells in the contributions
fragment`, and the regular expressions near the bottom of
`scripts/github_api.py` need updating.

### The Action ran but committed nothing

Expected whenever the regenerated SVGs are byte-identical to the committed
ones — no new contributions, no change in language bytes. The **Commit
refreshed assets** step logs `No asset changes to commit.` and the job passes.

If you expected a change, check the **Generate assets** step: each generator
runs in its own log group, and one failing does not stop the others. Any
failure is repeated in the job summary and turns the run red at the last step.

### The workflow fails to push

Confirm the workflow still declares `permissions: contents: write`, and that
repository **Settings** → **Actions** → **General** → **Workflow permissions**
is set to **Read and write permissions**.

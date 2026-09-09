"""Thin GitHub client used by the asset generators.

Resolves credentials through a three-tier strategy (PROFILE_TOKEN, then
GITHUB_TOKEN, then an unauthenticated fallback that scrapes the public
contributions fragment), caches every response as JSON under ``data/`` and
reuses a cached response while it is less than six hours old.

Exposes:
    resolve_auth()          -> AuthTier describing which tier is in play
    fetch_contributions()   -> ContributionCalendar
    fetch_language_bytes()  -> LanguageTotals

Not a general-purpose wrapper: it implements exactly the two queries the
generators need.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final

import requests

LOGGER = logging.getLogger(__name__)

USERNAME: Final[str] = "EvgenyBaulin"
CACHE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "data"
CACHE_TTL_SECONDS: Final[int] = 6 * 60 * 60
TIMEOUT: Final[int] = 30
MAX_ATTEMPTS: Final[int] = 3

API_ROOT: Final[str] = "https://api.github.com"
GRAPHQL_URL: Final[str] = f"{API_ROOT}/graphql"
CONTRIB_FRAGMENT_URL: Final[str] = f"https://github.com/users/{USERNAME}/contributions"

_USER_AGENT: Final[str] = "EvgenyBaulin-profile-assets/1.0"


class GitHubError(RuntimeError):
    """Raised when GitHub cannot be reached or returns an unusable response."""


class RateLimited(GitHubError):
    """Raised when the REST or GraphQL rate limit is exhausted."""


@dataclass(frozen=True)
class AuthTier:
    """Which credential tier the client resolved to."""

    tier: int
    name: str
    token: str | None

    @property
    def authenticated(self) -> bool:
        return self.token is not None


@dataclass
class ContributionCalendar:
    """A year of contribution activity.

    ``counts_available`` is False when the data came from the unauthenticated
    fragment and only intensity levels could be recovered. In that case
    ``total`` is None and callers must not print a total-contributions
    caption -- rendering a grid without a number is correct; inventing one is
    not.
    """

    days: list[dict[str, Any]] = field(default_factory=list)
    total: int | None = None
    counts_available: bool = False
    source: str = ""


@dataclass
class LanguageTotals:
    """Aggregated language byte counts across public non-fork repositories."""

    totals: dict[str, int] = field(default_factory=dict)
    repos_counted: int = 0
    partial: bool = False
    partial_reason: str = ""


def resolve_auth() -> AuthTier:
    """Resolve credentials, preferring PROFILE_TOKEN over GITHUB_TOKEN."""
    token = os.environ.get("PROFILE_TOKEN")
    if token:
        LOGGER.info("auth tier 1: using PROFILE_TOKEN")
        return AuthTier(1, "PROFILE_TOKEN", token)

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        LOGGER.info("auth tier 2: using GITHUB_TOKEN")
        return AuthTier(2, "GITHUB_TOKEN", token)

    LOGGER.warning(
        "auth tier 3: no token found; falling back to the public contributions "
        "fragment. Exact contribution counts may be unavailable."
    )
    return AuthTier(3, "unauthenticated", None)


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> Any | None:
    """Return a cached payload if it exists and is younger than the TTL."""
    path = _cache_path(key)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > CACHE_TTL_SECONDS:
        LOGGER.debug("cache %s is %.1fh old, ignoring", key, age / 3600)
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("cache %s is unreadable, ignoring", key)
        return None
    LOGGER.info("using cached %s (%.1fh old)", key, age / 3600)
    return payload


def _write_cache(key: str, payload: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _cache_path(key).write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:  # caching is best-effort, never fatal
        LOGGER.warning("could not write cache %s: %s", key, exc)


def _headers(auth: AuthTier, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": _USER_AGENT}
    if auth.token:
        headers["Authorization"] = f"Bearer {auth.token}"
    return headers


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Issue a request, retrying at most MAX_ATTEMPTS times on transport errors.

    Rate-limit responses are raised immediately rather than retried: looping
    against an exhausted quota only wastes time.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            LOGGER.warning("attempt %d/%d for %s failed: %s", attempt, MAX_ATTEMPTS, url, exc)
            continue

        if response.status_code in (403, 429) and _is_rate_limited(response):
            raise RateLimited(
                f"GitHub rate limit reached for {url}. "
                "Set PROFILE_TOKEN to raise the quota."
            )
        if response.status_code >= 500:
            last_exc = GitHubError(f"{url} returned {response.status_code}")
            LOGGER.warning("attempt %d/%d for %s: HTTP %d", attempt, MAX_ATTEMPTS, url, response.status_code)
            continue
        return response

    raise GitHubError(f"{url} failed after {MAX_ATTEMPTS} attempts: {last_exc}")


def _is_rate_limited(response: requests.Response) -> bool:
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    return "rate limit" in response.text.lower()


def fetch_contributions(auth: AuthTier) -> ContributionCalendar:
    """Fetch a year of contribution activity through the best available tier."""
    cached = _read_cache("contributions")
    if cached is not None:
        return ContributionCalendar(
            days=cached["days"],
            total=cached.get("total"),
            counts_available=cached.get("counts_available", False),
            source=cached.get("source", "cache"),
        )

    calendar = (
        _contributions_graphql(auth) if auth.authenticated else _contributions_scrape()
    )
    _write_cache(
        "contributions",
        {
            "days": calendar.days,
            "total": calendar.total,
            "counts_available": calendar.counts_available,
            "source": calendar.source,
        },
    )
    return calendar


def _contributions_graphql(auth: AuthTier) -> ContributionCalendar:
    """Authenticated path: the contributions calendar via GraphQL."""
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }
    """
    response = _request(
        "POST",
        GRAPHQL_URL,
        headers=_headers(auth),
        json={"query": query, "variables": {"login": USERNAME}},
    )
    if response.status_code != 200:
        raise GitHubError(f"GraphQL returned HTTP {response.status_code}: {response.text[:200]}")

    payload = response.json()
    if payload.get("errors"):
        raise GitHubError(f"GraphQL errors: {payload['errors']}")

    calendar_data = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days: list[dict[str, Any]] = []
    for week in calendar_data["weeks"]:
        for day in week["contributionDays"]:
            days.append({"date": day["date"], "count": day["contributionCount"], "level": None})

    levels = _levels_from_counts([d["count"] for d in days])
    for day, level in zip(days, levels):
        day["level"] = level

    LOGGER.info("GraphQL returned %d days, %d contributions", len(days), calendar_data["totalContributions"])
    return ContributionCalendar(
        days=days,
        total=int(calendar_data["totalContributions"]),
        counts_available=True,
        source="graphql",
    )


def _levels_from_counts(counts: list[int]) -> list[int]:
    """Bucket raw counts into GitHub's five intensity levels via quartiles."""
    active = sorted(c for c in counts if c > 0)
    if not active:
        return [0] * len(counts)
    cuts = [active[int(len(active) * q)] for q in (0.25, 0.5, 0.75)]
    levels = []
    for count in counts:
        if count <= 0:
            levels.append(0)
        elif count <= cuts[0]:
            levels.append(1)
        elif count <= cuts[1]:
            levels.append(2)
        elif count <= cuts[2]:
            levels.append(3)
        else:
            levels.append(4)
    return levels


# The fragment exposes data-date and data-level on each day cell. Exact counts
# live only in tooltip text and the markup changes periodically, so both
# patterns are tried and neither is required.
_CELL_RE: Final[re.Pattern[str]] = re.compile(
    r'<td[^>]*?data-date="(?P<date>\d{4}-\d{2}-\d{2})"[^>]*?data-level="(?P<level>\d+)"[^>]*?>',
    re.IGNORECASE,
)
_CELL_RE_ALT: Final[re.Pattern[str]] = re.compile(
    r'<td[^>]*?data-level="(?P<level>\d+)"[^>]*?data-date="(?P<date>\d{4}-\d{2}-\d{2})"[^>]*?>',
    re.IGNORECASE,
)
_ID_RE: Final[re.Pattern[str]] = re.compile(r'id="(contribution-day-component-[\w-]+)"')
_TOOLTIP_RE: Final[re.Pattern[str]] = re.compile(
    r'<tool-tip[^>]*?for="(?P<for>contribution-day-component-[\w-]+)"[^>]*?>(?P<body>.*?)</tool-tip>',
    re.IGNORECASE | re.DOTALL,
)
_COUNT_RE: Final[re.Pattern[str]] = re.compile(r"(?P<count>\d[\d,]*)\s+contribution", re.IGNORECASE)
# A day with no activity is spelled out in words rather than as a zero.
_NO_COUNT_RE: Final[re.Pattern[str]] = re.compile(r"\bno contributions\b", re.IGNORECASE)


def _count_from_tooltip(body: str) -> int | None:
    """Recover an exact contribution count from tooltip text, if it is there."""
    if _NO_COUNT_RE.search(body):
        return 0
    match = _COUNT_RE.search(body)
    if match:
        return int(match.group("count").replace(",", ""))
    return None


def _contributions_scrape() -> ContributionCalendar:
    """Unauthenticated fallback: parse the public contributions fragment.

    Levels are recoverable from the cell attributes. Counts are only present
    in tooltip text, which is the part of the markup that changes most often;
    when they cannot be recovered the calendar reports counts_available=False
    and callers omit the total caption.
    """
    response = _request(
        "GET",
        CONTRIB_FRAGMENT_URL,
        headers={"Accept": "text/html", "User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"},
    )
    if response.status_code != 200:
        raise GitHubError(
            f"contributions fragment returned HTTP {response.status_code}; "
            "the public fallback is unavailable"
        )

    html = response.text
    cells = list(_CELL_RE.finditer(html)) or list(_CELL_RE_ALT.finditer(html))
    if not cells:
        raise GitHubError(
            "could not find any day cells in the contributions fragment; "
            "the markup has changed and the parser needs updating"
        )

    tooltips = {m.group("for"): m.group("body") for m in _TOOLTIP_RE.finditer(html)}

    days: list[dict[str, Any]] = []
    counts_found = 0
    for cell in cells:
        tag = cell.group(0)
        count: int | None = None
        id_match = _ID_RE.search(tag)
        if id_match and id_match.group(1) in tooltips:
            count = _count_from_tooltip(tooltips[id_match.group(1)])
            if count is not None:
                counts_found += 1
        days.append(
            {
                "date": cell.group("date"),
                "count": count,
                "level": int(cell.group("level")),
            }
        )

    days.sort(key=lambda d: d["date"])
    counts_available = counts_found == len(days) and counts_found > 0
    total = sum(d["count"] or 0 for d in days) if counts_available else None

    if counts_available:
        LOGGER.info("fragment returned %d days with exact counts (total %d)", len(days), total)
    else:
        LOGGER.warning(
            "fragment returned %d days but only %d exact counts; rendering levels "
            "only and omitting the total caption",
            len(days),
            counts_found,
        )

    return ContributionCalendar(
        days=days,
        total=total,
        counts_available=counts_available,
        source="public-fragment",
    )


def fetch_language_bytes(auth: AuthTier) -> LanguageTotals:
    """Aggregate language byte counts over public, non-fork repositories.

    Unauthenticated REST is capped at 60 requests per hour. If the cap is hit
    partway through, whatever was retrieved is returned with ``partial`` set
    rather than retried in a loop.
    """
    cached = _read_cache("languages")
    if cached is not None:
        return LanguageTotals(
            totals={k: int(v) for k, v in cached["totals"].items()},
            repos_counted=cached.get("repos_counted", 0),
            partial=cached.get("partial", False),
            partial_reason=cached.get("partial_reason", ""),
        )

    repos = _list_public_repos(auth)
    totals: dict[str, int] = {}
    counted = 0
    partial = False
    reason = ""

    for repo in repos:
        try:
            response = _request("GET", repo["languages_url"], headers=_headers(auth))
        except RateLimited as exc:
            partial, reason = True, str(exc)
            LOGGER.warning("rate limit hit after %d repositories; using partial data", counted)
            break
        except GitHubError as exc:
            LOGGER.warning("skipping %s: %s", repo["name"], exc)
            continue

        if response.status_code != 200:
            LOGGER.warning("skipping %s: HTTP %d", repo["name"], response.status_code)
            continue

        for language, size in response.json().items():
            totals[language] = totals.get(language, 0) + int(size)
        counted += 1

    if not totals:
        raise GitHubError("no language data could be retrieved for any repository")

    result = LanguageTotals(totals=totals, repos_counted=counted, partial=partial, partial_reason=reason)
    _write_cache(
        "languages",
        {
            "totals": result.totals,
            "repos_counted": result.repos_counted,
            "partial": result.partial,
            "partial_reason": result.partial_reason,
        },
    )
    LOGGER.info("aggregated %d languages over %d repositories", len(totals), counted)
    return result


def _list_public_repos(auth: AuthTier) -> list[dict[str, Any]]:
    """List public, non-fork repositories owned by the profile user."""
    repos: list[dict[str, Any]] = []
    page = 1
    while True:
        response = _request(
            "GET",
            f"{API_ROOT}/users/{USERNAME}/repos",
            headers=_headers(auth),
            params={"per_page": 100, "page": page, "type": "owner", "sort": "pushed"},
        )
        if response.status_code != 200:
            raise GitHubError(f"listing repositories returned HTTP {response.status_code}")

        batch = response.json()
        if not batch:
            break
        repos.extend(r for r in batch if not r.get("fork") and not r.get("private"))
        if len(batch) < 100:
            break
        page += 1

    LOGGER.info("found %d public non-fork repositories", len(repos))
    return repos


def today() -> date:
    """Today's date. Wrapped so tests and callers share one clock."""
    return date.today()

#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

USERNAME = "vinialx"
SVG_PATH = Path("assets/profile.svg")
TOKEN = os.environ.get("GITHUB_TOKEN")

REST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"{USERNAME}-profile-generator",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    REST_HEADERS["Authorization"] = f"Bearer {TOKEN}"

LANGUAGE_COLORS = {
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Go": "#00add8",
    "Python": "#3572A5",
    "C": "#555555",
    "Lua": "#000080",
    "Nix": "#7e7eff",
    "Shell": "#89e051",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Dockerfile": "#384d54",
    "Rust": "#dea584",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Java": "#b07219",
}


def request_json(url: str, *, method="GET", payload=None, headers=None):
    final_headers = dict(REST_HEADERS)
    if headers:
        final_headers.update(headers)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=final_headers, method=method)
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def github_get(path: str):
    return request_json(f"https://api.github.com{path}")


def graphql(query: str, variables: dict):
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required for GraphQL profile data.")
    result = request_json(
        "https://api.github.com/graphql",
        method="POST",
        payload={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    if "errors" in result:
        raise RuntimeError(json.dumps(result["errors"], indent=2))
    return result["data"]


def fetch_all_repos():
    repos = []
    page = 1
    while True:
        batch = github_get(
            f"/users/{USERNAME}/repos?per_page=100&page={page}&type=owner&sort=updated"
        )
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_language_totals(repos):
    totals = defaultdict(int)
    for repo in repos:
        if repo.get("fork"):
            continue
        try:
            langs = github_get(f"/repos/{USERNAME}/{repo['name']}/languages")
        except Exception:
            continue
        for language, byte_count in langs.items():
            totals[language] += int(byte_count)
    return dict(totals)


def fetch_profile_graphql():
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
                contributionLevel
                weekday
              }
            }
          }
        }

        pinnedItems(first: 6, types: REPOSITORY) {
          nodes {
            ... on Repository {
              name
              url
              description
              stargazerCount
              forkCount
              primaryLanguage {
                name
                color
              }
            }
          }
        }
      }
    }
    """
    data = graphql(query, {"login": USERNAME})
    user = data["user"]
    calendar = user["contributionsCollection"]["contributionCalendar"]
    pins = [node for node in user["pinnedItems"]["nodes"] if node]
    return int(calendar["totalContributions"]), calendar["weeks"], pins


def replace_text(svg: str, element_id: str, value: str) -> str:
    pattern = rf'(<text id="{re.escape(element_id)}"[^>]*>)(.*?)(</text>)'
    return re.sub(pattern, rf"\g<1>{escape(str(value))}\g<3>", svg, flags=re.S)


def replace_group(svg: str, group_id: str, body: str) -> str:
    pattern = rf'(<g id="{re.escape(group_id)}">)(.*?)(</g>)'
    return re.sub(pattern, rf"\g<1>\n{body}\n\g<3>", svg, flags=re.S)


def render_languages(language_totals):
    total = sum(language_totals.values())
    if total <= 0:
        return '    <text x="70" y="492" fill="#64748b" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13">No language data available.</text>'

    ranked = sorted(language_totals.items(), key=lambda item: item[1], reverse=True)
    top = ranked[:7]
    remaining = sum(v for _, v in ranked[7:])
    if remaining:
        top.append(("Other", remaining))

    x0, y0, width, height = 70, 458, 1060, 18
    cursor = x0
    parts = []

    for language, count in top:
        pct = count / total
        segment = width * pct
        color = LANGUAGE_COLORS.get(language, "#64748b")
        if segment > 0.5:
            parts.append(
                f'    <rect x="{cursor:.2f}" y="{y0}" width="{segment:.2f}" height="{height}" rx="3" fill="{color}"/>'
            )
        cursor += segment

    legend_x, legend_y = 70, 506
    col_width = 250
    for i, (language, count) in enumerate(top):
        pct = count / total * 100
        col = i % 4
        row = i // 4
        lx = legend_x + col * col_width
        ly = legend_y + row * 28
        color = LANGUAGE_COLORS.get(language, "#64748b")
        parts.append(f'    <circle cx="{lx + 5}" cy="{ly - 5}" r="5" fill="{color}"/>')
        parts.append(
            f'    <text x="{lx + 18}" y="{ly}" fill="#cbd5e1" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13">{escape(language)} {pct:.1f}%</text>'
        )
    return "\n".join(parts)


def render_contribution_graph(weeks):
    level_colors = {
        "NONE": "#161b22",
        "FIRST_QUARTILE": "#0e4429",
        "SECOND_QUARTILE": "#006d32",
        "THIRD_QUARTILE": "#26a641",
        "FOURTH_QUARTILE": "#39d353",
    }

    x0, y0 = 70, 584
    cell, gap = 13, 4
    parts = []

    visible_weeks = weeks[-53:]
    for week_i, week in enumerate(visible_weeks):
        for day in week["contributionDays"]:
            weekday = int(day["weekday"])
            x = x0 + week_i * (cell + gap)
            y = y0 + weekday * (cell + gap)
            color = level_colors.get(day["contributionLevel"], "#161b22")
            count = int(day["contributionCount"])
            date = escape(day["date"])
            parts.append(
                f'    <rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}">'
                f'<title>{date}: {count} contribution{"s" if count != 1 else ""}</title></rect>'
            )

    lx = 984
    ly = 718
    parts.append(
        f'    <text x="{lx - 42}" y="{ly + 10}" fill="#64748b" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="11">less</text>'
    )
    for i, level in enumerate(["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]):
        parts.append(
            f'    <rect x="{lx + i * 18}" y="{ly}" width="12" height="12" rx="2" fill="{level_colors[level]}"/>'
        )
    parts.append(
        f'    <text x="{lx + 94}" y="{ly + 10}" fill="#64748b" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="11">more</text>'
    )
    return "\n".join(parts)


def truncate(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_pinned_repos(pins):
    if not pins:
        return '    <text x="70" y="798" fill="#64748b" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13">No pinned repositories found.</text>'

    parts = []
    box_w = 510
    box_h = 96
    gap_x = 30
    gap_y = 18
    start_x = 70
    start_y = 780

    for i, repo in enumerate(pins[:6]):
        col = i % 2
        row = i // 2
        x = start_x + col * (box_w + gap_x)
        y = start_y + row * (box_h + gap_y)

        name = escape(repo["name"])
        url = escape(repo["url"])
        desc = escape(truncate(repo.get("description"), 62))
        stars = int(repo.get("stargazerCount", 0))
        forks = int(repo.get("forkCount", 0))
        lang = repo.get("primaryLanguage") or {}
        lang_name = escape(lang.get("name") or "Unknown")
        lang_color = lang.get("color") or "#64748b"

        parts.append(f'    <a href="{url}" target="_blank">')
        parts.append(f'      <rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="14" fill="#10151c" stroke="#283240"/>')
        parts.append(f'      <text x="{x+20}" y="{y+28}" fill="#7dd3fc" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="16" font-weight="700">{name}</text>')
        parts.append(f'      <text x="{x+20}" y="{y+50}" fill="#94a3b8" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">{desc}</text>')
        parts.append(f'      <circle cx="{x+24}" cy="{y+75}" r="5" fill="{lang_color}"/>')
        parts.append(f'      <text x="{x+38}" y="{y+79}" fill="#cbd5e1" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">{lang_name}</text>')
        parts.append(f'      <text x="{x+360}" y="{y+79}" fill="#cbd5e1" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">★ {stars}   forks {forks}</text>')
        parts.append('    </a>')

    return "\n".join(parts)


def main():
    rest_user = github_get(f"/users/{USERNAME}")
    repos = fetch_all_repos()

    stars = sum(
        int(repo.get("stargazers_count", 0))
        for repo in repos
        if not repo.get("fork")
    )

    language_totals = fetch_language_totals(repos)
    contribution_total, weeks, pinned = fetch_profile_graphql()

    svg = SVG_PATH.read_text(encoding="utf-8")
    svg = replace_text(svg, "contributions", f"{contribution_total:,}")
    svg = replace_text(svg, "repos", f"{rest_user.get('public_repos', 0):,}")
    svg = replace_text(svg, "stars", f"{stars:,}")
    svg = replace_text(svg, "followers", f"{rest_user.get('followers', 0):,}")
    svg = replace_group(svg, "language-bars", render_languages(language_totals))
    svg = replace_group(svg, "contribution-graph", render_contribution_graph(weeks))
    svg = replace_group(svg, "pinned-repos", render_pinned_repos(pinned))
    SVG_PATH.write_text(svg, encoding="utf-8")

    total_lang_bytes = sum(language_totals.values())
    languages = {
        lang: round(count / total_lang_bytes * 100, 2)
        for lang, count in sorted(
            language_totals.items(),
            key=lambda item: item[1],
            reverse=True
        )
    } if total_lang_bytes else {}

    print(json.dumps({
        "username": USERNAME,
        "contributions_last_12_months": contribution_total,
        "public_repos": rest_user.get("public_repos", 0),
        "stars": stars,
        "followers": rest_user.get("followers", 0),
        "languages_percent": languages,
        "pinned_repositories": [repo["name"] for repo in pinned],
    }, indent=2))


if __name__ == "__main__":
    main()

"""
Hollywood Cricket Club — Weekly Site Updater
=============================================
Scrapes all 4 Hollywood team pages from cricclubs.com/SCCA and updates
hollywoodcc.html with the latest results, standings, batting, bowling,
upcoming fixtures, and scrolling ticker content.

Usage:
    python scraper.py                        # updates hollywoodcc.html in place
    python scraper.py --input path/to/file   # specify input HTML file
    python scraper.py --dry-run              # print what would change, don't write

Requirements:
    pip install requests beautifulsoup4 playwright
    playwright install chromium
"""

import re
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Config — team definitions
# ---------------------------------------------------------------------------

TEAMS = [
    {
        "num":      1,
        "label":    "HW1",
        "name":     "Hollywood 1",
        "division": "2026 OD Div 1",
        "series_id":"E3fP_GI8dqYYOIeCUnfTcw",
        "team_hash":"YPCtBhfsGB5qjfklxBLPKA",
        "color":    "#1A5C3A",
    },
    {
        "num":      2,
        "label":    "HW2",
        "name":     "Hollywood 2",
        "division": "2026 OD Div 2",
        "series_id":"jqVCP7p_259dJv6vajaYYg",
        "team_hash":"31c2kEqdnKzxl7mDVNZVUg",
        "color":    "#1B3F6E",
    },
    {
        "num":      3,
        "label":    "HW3",
        "name":     "Hollywood 3",
        "division": "2026 OD Div 3",
        "series_id":"betgectBJ7qRH8CajBaROA",
        "team_hash":"SE8vSPGlCNuAIFcV1b4s_g",
        "color":    "#4A2B7A",
    },
    {
        "num":      4,
        "label":    "HW4",
        "name":     "Hollywood 4",
        "division": "2026 OD Div 5",
        "series_id":"f6ZxqbZmn6o9A4WC9BQknA",
        "team_hash":"fN3_xwJQQaRxvMia4RQzPg",
        "color":    "#8B2020",
    },
]

BASE_URL   = "https://cricclubs.com/SCCA"
SERIES_URL = BASE_URL + "/series-list/{series_id}?seriesName={div}&tab={tab}"
TEAM_URL   = BASE_URL + "/teams/{team_hash}?seriesId={series_id}&tab={tab}"

# How many recent results / upcoming fixtures to show in the ticker
TICKER_RESULTS_PER_TEAM  = 3
TICKER_UPCOMING_PER_TEAM = 2
TICKER_PLAYERS_PER_TEAM  = 2

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("hcc")


# ---------------------------------------------------------------------------
# Browser-based scraping (CricClubs is a React SPA — needs JS execution)
# ---------------------------------------------------------------------------

def get_page_text(page, url: str) -> str:
    """Navigate to url, wait for content, return page text."""
    page.goto(url, wait_until="networkidle", timeout=30_000)
    return page.inner_text("body")


def scrape_points_table(page, team: dict) -> list[dict]:
    """
    Returns the full points table for the division as a list of dicts:
    [{pos, team, mat, won, lost, nr, tie, pts, win_pct, nrr}, ...]
    """
    url  = SERIES_URL.format(
        series_id=team["series_id"],
        div=team["division"].replace(" ", "+"),
        tab="pointsTable",
    )
    text = get_page_text(page, url)
    rows = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Find the table block — look for lines that are just numbers after a team name
    in_table = False
    pos = 0
    i   = 0
    while i < len(lines):
        if "Points Table" in lines[i] and "Details" not in lines[i]:
            in_table = True
            i += 1
            continue
        if in_table:
            # Each row looks like: pos / team-name / mat / won / lost / n/r / tie / pts / win% / nrr / for / against
            if lines[i].lstrip("#").strip().isdigit():
                try:
                    pos       = int(lines[i].lstrip("#").strip())
                    team_name = lines[i+1].strip() if i+1 < len(lines) else ""
                    # skip logo line if present
                    offset = 2
                    nums = []
                    while len(nums) < 9 and (i + offset) < len(lines):
                        candidate = lines[i + offset].strip()
                        # accept numbers, percentages, negative numbers, decimals
                        if re.match(r'^-?\d+\.?\d*%?$', candidate):
                            nums.append(candidate)
                        elif re.match(r'^\d+/\d+\.\d+$', candidate):  # "for" column e.g. 964/213.3
                            nums.append(candidate)
                        offset += 1
                    if len(nums) >= 7:
                        rows.append({
                            "pos":     pos,
                            "team":    team_name,
                            "mat":     int(nums[0]),
                            "won":     int(nums[1]),
                            "lost":    int(nums[2]),
                            "nr":      int(nums[3]),
                            "tie":     int(nums[4]),
                            "pts":     int(nums[5]),
                            "win_pct": nums[6],
                            "nrr":     nums[7] if len(nums) > 7 else "0",
                        })
                except (ValueError, IndexError):
                    pass
                i += offset
                continue
            # End of table detection
            if "©" in lines[i] or "All rights" in lines[i]:
                break
        i += 1
    return rows


def scrape_team_results(page, team: dict) -> list[dict]:
    """Returns list of completed match results for the team."""
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="results",
    )
    text = get_page_text(page, url)
    results = []
    lines   = [l.strip() for l in text.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        # Date lines look like "Saturday, May 17, 2026 10:00 AM"
        date_match = re.match(
            r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
            r'(\w+ \d+, \d{4})',
            lines[i]
        )
        if date_match:
            date_str = date_match.group(2)          # e.g. "May 17, 2026"
            # Look ahead for scores and result
            block = lines[i:i+20]
            block_text = " | ".join(block)

            # Extract scores  e.g. "167/6(38.5/50)"
            scores = re.findall(r'\d+/\d+\(\d+\.?\d*/\d+\)', block_text)

            # Extract result line  e.g. "Hollywood 1 won by 4 Wickets"
            result_line = ""
            for l in block:
                if re.search(r'\b(won|lost|tied|Tie|Abandoned|No result)\b', l, re.I):
                    if not any(x in l for x in ["Scorecard", "Ball by Ball", "Umpire"]):
                        result_line = l.strip()
                        break

            # Opponent and venue
            opponent = ""
            venue    = ""
            for idx, bl in enumerate(block):
                if bl in ["League", "2026 OD Div 1", "2026 OD Div 2",
                          "2026 OD Div 3", "2026 OD Div 5"]:
                    if idx + 1 < len(block):
                        venue = block[idx + 1]
                    break
            # Find opponent — team that is NOT us
            team_name = team["name"]
            for bl in block:
                if "vs" in bl.lower():
                    parts = re.split(r'\s+vs\s+', bl, flags=re.I)
                    for p in parts:
                        p = p.strip()
                        if p and team_name not in p and len(p) > 2:
                            opponent = p
                            break
                    break

            if result_line:
                # Normalise result
                hw_score   = scores[0] if len(scores) > 0 else ""
                opp_score  = scores[1] if len(scores) > 1 else ""
                # Determine W/L/T
                rl = result_line.lower()
                if "tie" in rl or "tied" in rl:
                    outcome = "T"
                elif "abandoned" in rl or "no result" in rl:
                    outcome = "NR"
                elif team_name.lower() in rl and ("won" in rl or "win" in rl):
                    outcome = "W"
                elif team_name.lower() in rl and "won" not in rl:
                    outcome = "L"
                elif "won" in rl:
                    # Check if hw team is the winner
                    winner_part = result_line.split("won")[0].strip()
                    outcome = "W" if team_name.lower() in winner_part.lower() else "L"
                else:
                    outcome = "?"

                results.append({
                    "date":      date_str,
                    "opponent":  opponent,
                    "venue":     venue,
                    "hw_score":  hw_score,
                    "opp_score": opp_score,
                    "result":    result_line,
                    "outcome":   outcome,
                })
        i += 1
    return results


def scrape_team_schedule(page, team: dict) -> list[dict]:
    """Returns upcoming fixtures."""
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="schedule",
    )
    text = get_page_text(page, url)
    upcoming = []
    lines    = [l.strip() for l in text.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        date_match = re.match(
            r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
            r'(\w+ \d+, \d{4})',
            lines[i]
        )
        if date_match:
            date_str = date_match.group(2)
            block    = lines[i:i+15]
            # Upcoming: no score lines present
            has_score = any(re.search(r'\d+/\d+\(', bl) for bl in block)
            if not has_score:
                opponent = ""
                venue    = ""
                for idx, bl in enumerate(block):
                    if bl in ["League", "2026 OD Div 1", "2026 OD Div 2",
                              "2026 OD Div 3", "2026 OD Div 5"]:
                        if idx + 1 < len(block):
                            venue = block[idx + 1]
                        break
                for bl in block:
                    if "vs" in bl.lower():
                        parts = re.split(r'\s+vs\s+', bl, flags=re.I)
                        for p in parts:
                            p = p.strip()
                            if p and team["name"] not in p and len(p) > 2:
                                opponent = p
                                break
                        break
                if opponent:
                    upcoming.append({
                        "date":     date_str,
                        "opponent": opponent,
                        "venue":    venue,
                    })
        i += 1
    return upcoming


def scrape_batting(page, team: dict) -> list[dict]:
    """Returns top batting stats."""
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="batting",
    )
    text  = get_page_text(page, url)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    stats = []
    i     = 0
    while i < len(lines):
        # Row starts with a rank number
        if re.match(r'^\d+$', lines[i]) and i + 14 < len(lines):
            try:
                rank    = int(lines[i])
                name    = lines[i+1]
                # Skip "Hollywood N" team label
                offset  = 3 if lines[i+2].startswith("Hollywood") else 2
                vals    = lines[i+offset:i+offset+12]
                nums    = [v for v in vals if re.match(r'^-?\d+\.?\d*$', v)]
                if len(nums) >= 10:
                    stats.append({
                        "rank":    rank,
                        "name":    name,
                        "mat":     int(nums[0]),
                        "inns":    int(nums[1]),
                        "no":      int(nums[2]),
                        "runs":    int(nums[3]),
                        "balls":   int(nums[4]),
                        "fours":   int(nums[5]),
                        "sixes":   int(nums[6]),
                        "fifties": int(nums[7]),
                        "hundreds":int(nums[8]),
                        "hs":      int(nums[9])  if len(nums) > 9  else 0,
                        "sr":      float(nums[10]) if len(nums) > 10 else 0.0,
                        "avg":     float(nums[11]) if len(nums) > 11 else 0.0,
                    })
            except (ValueError, IndexError):
                pass
        i += 1
    return stats


def scrape_bowling(page, team: dict) -> list[dict]:
    """Returns top bowling stats."""
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="bowling",
    )
    text  = get_page_text(page, url)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    stats = []
    i     = 0
    while i < len(lines):
        if re.match(r'^\d+$', lines[i]) and i + 14 < len(lines):
            try:
                rank   = int(lines[i])
                name   = lines[i+1]
                offset = 3 if lines[i+2].startswith("Hollywood") else 2
                vals   = lines[i+offset:i+offset+14]
                nums   = [v for v in vals if re.match(r'^-?\d+\.?\d*$', v)]
                # BBF e.g. "4/36" — extract separately
                bbf_matches = [v for v in vals if re.match(r'^\d+/\d+$', v)]
                bbf = bbf_matches[0] if bbf_matches else "0/0"
                if len(nums) >= 8:
                    stats.append({
                        "rank": rank,
                        "name": name,
                        "mat":  int(nums[0]),
                        "overs":float(nums[2]) if len(nums) > 2 else 0.0,
                        "mdns": int(nums[3])   if len(nums) > 3 else 0,
                        "runs": int(nums[4])   if len(nums) > 4 else 0,
                        "wkts": int(nums[5])   if len(nums) > 5 else 0,
                        "bbf":  bbf,
                        "econ": float(nums[7]) if len(nums) > 7 else 0.0,
                        "avg":  float(nums[8]) if len(nums) > 8 else 0.0,
                        "sr":   float(nums[9]) if len(nums) > 9 else 0.0,
                    })
            except (ValueError, IndexError):
                pass
        i += 1
    return stats


# ---------------------------------------------------------------------------
# HTML injection helpers
# ---------------------------------------------------------------------------

def js_array_of_dicts(rows: list[dict]) -> str:
    """Convert list of dicts to a compact JS array literal."""
    parts = []
    for row in rows:
        inner = ",".join(f"{k}:{json.dumps(v)}" for k, v in row.items())
        parts.append("{" + inner + "}")
    return "[\n      " + ",\n      ".join(parts) + "\n    ]"


def build_team_js_block(team_cfg: dict, data: dict) -> str:
    """
    Returns the replacement JS object for one team inside TEAMS_DATA.
    Preserves all static fields (color, description, cricUrl, roster, etc.)
    and replaces dynamic fields (record, results, upcoming, batting, bowling).
    """
    t   = team_cfg
    d   = data

    # Record
    results  = d["results"]
    w  = sum(1 for r in results if r["outcome"] == "W")
    l  = sum(1 for r in results if r["outcome"] == "L")
    tie= sum(1 for r in results if r["outcome"] == "T")
    nr = sum(1 for r in results if r["outcome"] == "NR")
    p  = w + l + tie + nr

    # Find our position in standings
    pos = next(
        (s["pos"] for s in d["standings"] if team_cfg["name"] in s["team"]),
        "–"
    )
    nrr_raw = next(
        (s["nrr"] for s in d["standings"] if team_cfg["name"] in s["team"]),
        "0"
    )
    try:
        nrr = float(nrr_raw)
    except ValueError:
        nrr = 0.0

    # Serialise results
    results_js = "[\n"
    for r in results[:8]:
        outcome_label = (
            f"W by {r['result'].split('by',1)[1].strip()}" if r["outcome"] == "W" and "by" in r["result"]
            else f"L by {r['result'].split('by',1)[1].strip()}" if r["outcome"] == "L" and "by" in r["result"]
            else r["outcome"]
        )
        results_js += (
            f"      {{date:'{r['date']}',opp:'{r['opponent'].replace(chr(39),'')}'"
            f",venue:'{r['venue'].replace(chr(39),'')}'"
            f",hw1:'{r['hw_score']}',opp_score:'{r['opp_score']}'"
            f",result:'{outcome_label.replace(chr(39),'')}'}},"
            "\n"
        )
    results_js += "    ]"

    # Serialise upcoming
    upcoming_js = "[\n"
    for u in d["upcoming"][:4]:
        upcoming_js += (
            f"      {{date:'{u['date']}'"
            f",opp:'{u['opponent'].replace(chr(39),'')}'"
            f",venue:'{u['venue'].replace(chr(39),'')}'"
            f",home:false}},\n"
        )
    upcoming_js += "    ]"

    # Serialise batting top 10
    batting_js = "[\n"
    for b in d["batting"][:10]:
        batting_js += (
            f"      {{rank:{b['rank']},name:'{b['name'].replace(chr(39),'')}'"
            f",mat:{b['mat']},inns:{b['inns']},no:{b['no']},runs:{b['runs']}"
            f",balls:{b['balls']},fours:{b['fours']},sixes:{b['sixes']}"
            f",fifties:{b['fifties']},hundreds:{b['hundreds']},hs:{b['hs']}"
            f",sr:{b['sr']},avg:{b['avg']}}},\n"
        )
    batting_js += "    ]"

    # Serialise bowling top 8
    bowling_js = "[\n"
    for bw in d["bowling"][:8]:
        bowling_js += (
            f"      {{rank:{bw['rank']},name:'{bw['name'].replace(chr(39),'')}'"
            f",mat:{bw['mat']},overs:{bw['overs']},mdns:{bw['mdns']}"
            f",runs:{bw['runs']},wkts:{bw['wkts']},bbf:'{bw['bbf']}'"
            f",econ:{bw['econ']},avg:{bw['avg']},sr:{bw['sr']}}},\n"
        )
    bowling_js += "    ]"

    return (
        f"record:{{p:{p},w:{w},l:{l},t:{tie},nrr:{nrr:.4f}}}",
        results_js,
        upcoming_js,
        batting_js,
        bowling_js,
    )


def build_standings_rows(all_standings: dict) -> str:
    """Build the HTML rows for the home-page standings table."""
    div_colors = {1: "#1A5C3A", 2: "#1B3F6E", 3: "#4A2B7A", 4: "#8B2020"}
    div_labels = {1: "2026 OD Div 1", 2: "2026 OD Div 2",
                  3: "2026 OD Div 3", 4: "2026 OD Div 5"}
    rows = ""
    for num, t in enumerate(TEAMS, 1):
        color = div_colors[num]
        label = div_labels[num]
        team_name_html = f"Hollywood {num}"
        standings = all_standings.get(num, [])
        entry = next(
            (s for s in standings if f"Hollywood {num}" in s["team"]),
            None
        )
        # Header row for this division
        rows += (
            f'<tr style="background:#f0f4ff">'
            f'<td colspan="8" style="padding:8px 14px;font-size:11px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:.08em;color:{color}">'
            f'{label} — {team_name_html}</td></tr>\n'
        )
        if entry:
            nrr     = entry["nrr"]
            try:
                nrr_f = float(nrr)
                nrr_col = "#27ae60" if nrr_f >= 0 else "#c0392b"
                nrr_str = f"+{nrr_f:.4f}" if nrr_f >= 0 else f"{nrr_f:.4f}"
            except ValueError:
                nrr_col = "#555"
                nrr_str = nrr
            tie_nr = entry["tie"] + entry["nr"]
            rows += (
                f'<tr class="hw-row">'
                f'<td><strong>{entry["pos"]}</strong></td>'
                f'<td><strong>{team_name_html}</strong></td>'
                f'<td>{entry["mat"]}</td><td>{entry["won"]}</td>'
                f'<td>{entry["lost"]}</td><td>{tie_nr}</td>'
                f'<td>{entry["pts"]}</td>'
                f'<td style="font-size:12px;color:{nrr_col}">{nrr_str}</td>'
                f'</tr>\n'
            )
        else:
            rows += (
                f'<tr class="hw-row"><td>–</td><td><strong>{team_name_html}</strong></td>'
                f'<td colspan="6" style="color:#999">No data</td></tr>\n'
            )
    return rows


def build_ticker_items(all_data: dict) -> str:
    """Build all ticker <div> items (deduplicated — the HTML already doubles them)."""
    items = []

    def item(tag_cls, tag_text, text):
        return (
            f'<div class="ticker-item">'
            f'<span class="ticker-tag {tag_cls}">{tag_text}</span> '
            f'{text}'
            f'</div>'
        )

    # Upcoming fixtures
    for t in TEAMS:
        num  = t["num"]
        upcoming = all_data[num]["upcoming"][:TICKER_UPCOMING_PER_TEAM]
        for u in upcoming:
            items.append(item(
                "upcoming", "Upcoming",
                f'{t["label"]} vs {u["opponent"]} &mdash; {u["date"]}'
                + (f' &bull; {u["venue"]}' if u["venue"] else "")
            ))

    # Recent results
    for t in TEAMS:
        num     = t["num"]
        results = all_data[num]["results"][:TICKER_RESULTS_PER_TEAM]
        for r in results:
            oc = r["outcome"]
            if oc == "W":
                tag_cls, tag_text = "win",  "Result"
                verb = "beat"
            elif oc == "T":
                tag_cls, tag_text = "tie",  "Result"
                verb = "tied with"
            elif oc == "NR":
                tag_cls, tag_text = "tie",  "Result"
                verb = "vs"
            else:
                tag_cls, tag_text = "loss", "Result"
                verb = "lost to"

            # Extract margin
            margin = ""
            if "by" in r["result"].lower():
                margin = " " + r["result"].split("by", 1)[1].strip()

            # Short date e.g. "May 17"
            short_date = " ".join(r["date"].split(",")[-1].strip().split()[:2]) \
                         if "," in r["date"] else r["date"]

            items.append(item(
                tag_cls, tag_text,
                f'{t["label"]} {verb} {r["opponent"]}'
                + (f' by{margin}' if margin else "")
                + f' &mdash; {short_date}'
            ))

    # Player highlights — top batter and top bowler per team
    for t in TEAMS:
        num     = t["num"]
        batting = all_data[num]["batting"]
        bowling = all_data[num]["bowling"]

        if batting:
            b = batting[0]
            items.append(item(
                "highlight", "&#9733; Player",
                f'{b["name"]} ({t["label"]}) &mdash; {b["runs"]} runs'
                + (f', {b["fifties"]} fifties' if b["fifties"] else "")
                + f', avg {b["avg"]:.2f}'
            ))

        if bowling:
            bw = bowling[0]
            items.append(item(
                "highlight", "&#9733; Player",
                f'{bw["name"]} ({t["label"]}) &mdash; {bw["wkts"]} wkts'
                + (f' incl {bw["bbf"]}' if bw["bbf"] != "0/0" else "")
                + f', econ {bw["econ"]:.2f}'
            ))

    # Standings snapshots for teams with wins
    for t in TEAMS:
        num   = t["num"]
        stgds = all_data[num]["standings"]
        entry = next(
            (s for s in stgds if f'Hollywood {num}' in s["team"]), None
        )
        if entry and entry["won"] > 0:
            try:
                nrr_f = float(entry["nrr"])
                nrr_s = f'+{nrr_f:.2f}' if nrr_f >= 0 else f'{nrr_f:.2f}'
            except ValueError:
                nrr_s = entry["nrr"]
            items.append(item(
                "highlight", "Standings",
                f'{t["label"]} sit {entry["pos"]}{"st" if entry["pos"]==1 else "nd" if entry["pos"]==2 else "rd" if entry["pos"]==3 else "th"}'
                f' in {t["division"]} &mdash; '
                f'{entry["won"]}W {entry["lost"]}L, {entry["pts"]} pts, NRR {nrr_s}'
            ))

    return "\n        ".join(items)


# ---------------------------------------------------------------------------
# HTML updater
# ---------------------------------------------------------------------------

def update_html(html: str, all_data: dict) -> str:
    """Apply all data updates to the HTML string and return the new HTML."""

    # 1. Update "last updated" date in standings description
    today = datetime.now().strftime("%B %-d, %Y")
    html  = re.sub(
        r'Live standings as of [^.]+\.',
        f'Live standings as of {today}.',
        html
    )

    # 2. Update standings table rows
    new_rows = build_standings_rows({t["num"]: all_data[t["num"]]["standings"] for t in TEAMS})
    html = re.sub(
        r'(<!-- STANDINGS_ROWS_START -->).*?(<!-- STANDINGS_ROWS_END -->)',
        f'<!-- STANDINGS_ROWS_START -->\n{new_rows}<!-- STANDINGS_ROWS_END -->',
        html, flags=re.DOTALL
    )
    # Fallback: replace the hw-row block directly if markers aren't present
    if "<!-- STANDINGS_ROWS_START -->" not in html:
        html = re.sub(
            r'(<tr style="background:#f0f4ff"><td colspan="8"[^>]*>2026 OD Div 1).*?'
            r'(</tr>\s*</tbody>)',
            new_rows + r'\2',
            html, flags=re.DOTALL
        )

    # 3. Update TEAMS_DATA JS block for each team
    for t in TEAMS:
        num  = t["num"]
        d    = all_data[num]
        record_js, results_js, upcoming_js, batting_js, bowling_js = \
            build_team_js_block(t, d)

        # Replace record:{...}
        html = re.sub(
            rf'(// team {num} start.*?)?record:\{{p:\d+,w:\d+,l:\d+,t:\d+[^}}]*\}}',
            record_js,
            html, count=1
        )

        # Replace results:[...] for this team
        # We identify the Nth occurrence (team num)
        results_pattern = r'results:\[.*?\](?=,\s*\n\s*upcoming:)'
        matches = list(re.finditer(results_pattern, html, re.DOTALL))
        if len(matches) >= num:
            m   = matches[num - 1]
            html = html[:m.start()] + f'results:{results_js}' + html[m.end():]

        # Replace upcoming:[...]
        upcoming_pattern = r'upcoming:\[.*?\](?=,\s*\n\s*batting:)'
        matches = list(re.finditer(upcoming_pattern, html, re.DOTALL))
        if len(matches) >= num:
            m   = matches[num - 1]
            html = html[:m.start()] + f'upcoming:{upcoming_js}' + html[m.end():]

        # Replace batting:[...]
        batting_pattern = r'batting:\[.*?\](?=,\s*\n\s*bowling:)'
        matches = list(re.finditer(batting_pattern, html, re.DOTALL))
        if len(matches) >= num:
            m   = matches[num - 1]
            html = html[:m.start()] + f'batting:{batting_js}' + html[m.end():]

        # Replace bowling:[...]
        bowling_pattern = r'bowling:\[.*?\](?=,\s*\n\s*fielding:)'
        matches = list(re.finditer(bowling_pattern, html, re.DOTALL))
        if len(matches) >= num:
            m   = matches[num - 1]
            html = html[:m.start()] + f'bowling:{bowling_js}' + html[m.end():]

    # 4. Replace ticker items (everything between the ticker-inner divs)
    new_ticker = build_ticker_items(all_data)
    # Double it for seamless looping
    ticker_doubled = new_ticker + "\n        " + new_ticker
    html = re.sub(
        r'(<div class="ticker-inner"[^>]*>)\s*.*?(\s*</div>\s*</div>\s*</div>)',
        rf'\g<1>\n        {ticker_doubled}\n      \g<2>',
        html, flags=re.DOTALL, count=1
    )

    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HCC weekly site updater")
    parser.add_argument("--input",   default="hollywoodcc.html",
                        help="Path to hollywoodcc.html (default: ./hollywoodcc.html)")
    parser.add_argument("--output",  default=None,
                        help="Output path (default: same as input)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print summary of changes without writing file")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        return

    # ── Scrape ──────────────────────────────────────────────────────────────
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright not installed. Run: pip install playwright && playwright install chromium")
        return

    all_data = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_page()
        page.set_default_timeout(30_000)

        for t in TEAMS:
            num = t["num"]
            log.info(f"Scraping {t['name']} ({t['division']}) ...")

            standings = scrape_points_table(page, t)
            log.info(f"  Standings: {len(standings)} teams")

            results   = scrape_team_results(page, t)
            log.info(f"  Results:   {len(results)} matches")

            upcoming  = scrape_team_schedule(page, t)
            log.info(f"  Upcoming:  {len(upcoming)} fixtures")

            batting   = scrape_batting(page, t)
            log.info(f"  Batting:   {len(batting)} players")

            bowling   = scrape_bowling(page, t)
            log.info(f"  Bowling:   {len(bowling)} players")

            all_data[num] = {
                "standings": standings,
                "results":   results,
                "upcoming":  upcoming,
                "batting":   batting,
                "bowling":   bowling,
            }

        browser.close()

    # ── Update HTML ──────────────────────────────────────────────────────────
    html     = input_path.read_text(encoding="utf-8")
    new_html = update_html(html, all_data)

    if args.dry_run:
        log.info("Dry run — no file written.")
        for t in TEAMS:
            num = t["num"]
            d   = all_data[num]
            w   = sum(1 for r in d["results"] if r["outcome"] == "W")
            l   = sum(1 for r in d["results"] if r["outcome"] == "L")
            print(f"\n{t['name']}: {w}W {l}L | "
                  f"{len(d['upcoming'])} upcoming | "
                  f"Top bat: {d['batting'][0]['name']} {d['batting'][0]['runs']} runs | "
                  f"Top bowl: {d['bowling'][0]['name']} {d['bowling'][0]['wkts']} wkts"
                  if d["batting"] and d["bowling"] else f"\n{t['name']}: scraped")
    else:
        output_path.write_text(new_html, encoding="utf-8")
        log.info(f"Updated: {output_path}")
        log.info(f"Done — {datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()

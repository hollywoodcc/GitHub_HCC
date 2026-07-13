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
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path

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

# Ticker config
TICKER_RESULTS_PER_TEAM  = 3
TICKER_UPCOMING_PER_TEAM = 2
TICKER_PLAYERS_PER_TEAM  = 2

# ---------------------------------------------------------------------------
# Timeouts & retry config  ← KEY FIX
# ---------------------------------------------------------------------------
PAGE_TIMEOUT   = 60_000   # 60s total page load timeout
WAIT_AFTER_NAV = 4        # seconds to wait after navigation for JS to render
MAX_RETRIES    = 3        # retry each page this many times on failure

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("hcc")


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def get_page_text(page, url: str) -> str:
    """
    Navigate to url and return page body text.

    KEY FIXES vs original:
    - wait_until="domcontentloaded"  (not "networkidle" — CricClubs SPA never
      reaches networkidle because it keeps polling in the background)
    - Extra time.sleep() after navigation so the React components can render
    - Retry loop with exponential back-off
    """
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",   # ← was "networkidle" — FIXED
                timeout=PAGE_TIMEOUT,
            )
            # Give the React SPA time to render data into the DOM
            time.sleep(WAIT_AFTER_NAV)
            return page.inner_text("body")
        except Exception as e:
            last_err = e
            log.warning(f"  Attempt {attempt}/{MAX_RETRIES} failed for {url}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)   # back-off: 5s, 10s …
    raise RuntimeError(f"Failed to load {url} after {MAX_RETRIES} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

def scrape_points_table(page, team: dict) -> list:
    url  = SERIES_URL.format(
        series_id=team["series_id"],
        div=team["division"].replace(" ", "+"),
        tab="pointsTable",
    )
    log.info(f"  Fetching standings: {url}")
    text = get_page_text(page, url)
    rows = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    in_table = False
    i = 0
    while i < len(lines):
        if "Points Table" in lines[i] and "Details" not in lines[i]:
            in_table = True
            i += 1
            continue
        if in_table:
            if re.match(r'^\d+$', lines[i].lstrip("#").strip()):
                try:
                    pos       = int(lines[i].lstrip("#").strip())
                    team_name = lines[i+1].strip() if i+1 < len(lines) else ""
                    offset    = 2
                    nums      = []
                    while len(nums) < 9 and (i + offset) < len(lines):
                        candidate = lines[i + offset].strip()
                        if re.match(r'^-?\d+\.?\d*%?$', candidate):
                            nums.append(candidate)
                        elif re.match(r'^\d+/\d+\.\d+$', candidate):
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
                            "pts":     int(float(nums[5])),
                            "win_pct": nums[6],
                            "nrr":     nums[7] if len(nums) > 7 else "0",
                        })
                except (ValueError, IndexError):
                    pass
                i += offset
                continue
            if "©" in lines[i] or "All rights" in lines[i]:
                break
        i += 1
    log.info(f"  → {len(rows)} teams in standings")
    return rows


def scrape_team_results(page, team: dict) -> list:
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="results",
    )
    log.info(f"  Fetching results: {url}")
    text    = get_page_text(page, url)
    results = []
    lines   = [l.strip() for l in text.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        date_match = re.match(
            r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
            r'(\w+ \d+, \d{4})',
            lines[i]
        )
        if date_match:
            date_str   = date_match.group(2)
            block      = lines[i:i+20]
            block_text = " | ".join(block)
            scores     = re.findall(r'\d+/\d+\(\d+\.?\d*/\d+\)', block_text)
            result_line = ""
            for l in block:
                if re.search(r'\b(won|lost|tied|Tie|Abandoned|No result)\b', l, re.I):
                    if not any(x in l for x in ["Scorecard", "Ball by Ball", "Umpire"]):
                        result_line = l.strip()
                        break
            opponent = ""
            venue    = ""
            for idx, bl in enumerate(block):
                if bl in ["League", "2026 OD Div 1", "2026 OD Div 2",
                          "2026 OD Div 3", "2026 OD Div 5"]:
                    if idx + 1 < len(block):
                        venue = block[idx + 1]
                    break
            team_name = team["name"]
            for bl in block:
                if re.search(r'\bvs\b', bl, re.I):
                    parts = re.split(r'\s+vs\s+', bl, flags=re.I)
                    for p in parts:
                        p = p.strip()
                        if p and team_name not in p and len(p) > 2:
                            opponent = p
                            break
                    break
            if result_line:
                rl = result_line.lower()
                if "tie" in rl or "tied" in rl:
                    outcome = "T"
                elif "abandoned" in rl or "no result" in rl:
                    outcome = "NR"
                else:
                    winner_part = result_line.split("won")[0].strip() if "won" in result_line.lower() else ""
                    outcome = "W" if team_name.lower() in winner_part.lower() else "L"

                results.append({
                    "date":      date_str,
                    "opponent":  opponent,
                    "venue":     venue,
                    "hw_score":  scores[0] if scores else "",
                    "opp_score": scores[1] if len(scores) > 1 else "",
                    "result":    result_line,
                    "outcome":   outcome,
                })
        i += 1
    log.info(f"  → {len(results)} results")
    return results


def scrape_team_schedule(page, team: dict) -> list:
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="schedule",
    )
    log.info(f"  Fetching schedule: {url}")
    text     = get_page_text(page, url)
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
                    if re.search(r'\bvs\b', bl, re.I):
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
    log.info(f"  → {len(upcoming)} upcoming fixtures")
    return upcoming


def scrape_batting(page, team: dict) -> list:
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="batting",
    )
    log.info(f"  Fetching batting: {url}")
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
                if len(nums) >= 10:
                    stats.append({
                        "rank":     rank,
                        "name":     name,
                        "mat":      int(nums[0]),
                        "inns":     int(nums[1]),
                        "no":       int(nums[2]),
                        "runs":     int(nums[3]),
                        "balls":    int(nums[4]),
                        "fours":    int(nums[5]),
                        "sixes":    int(nums[6]),
                        "fifties":  int(nums[7]),
                        "hundreds": int(nums[8]),
                        "hs":       int(nums[9])   if len(nums) > 9  else 0,
                        "sr":       float(nums[10]) if len(nums) > 10 else 0.0,
                        "avg":      float(nums[11]) if len(nums) > 11 else 0.0,
                    })
            except (ValueError, IndexError):
                pass
        i += 1
    log.info(f"  → {len(stats)} batters")
    return stats


def scrape_bowling(page, team: dict) -> list:
    url  = TEAM_URL.format(
        team_hash=team["team_hash"],
        series_id=team["series_id"],
        tab="bowling",
    )
    log.info(f"  Fetching bowling: {url}")
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
                vals   = lines[i+offset:i+offset+16]
                nums   = [v for v in vals if re.match(r'^-?\d+\.?\d*$', v)]
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
    log.info(f"  → {len(stats)} bowlers")
    return stats


# ---------------------------------------------------------------------------
# HTML injection helpers
# ---------------------------------------------------------------------------

def build_standings_rows(all_standings: dict) -> str:
    div_colors = {1:"#1A5C3A", 2:"#1B3F6E", 3:"#4A2B7A", 4:"#8B2020"}
    div_labels = {1:"2026 OD Div 1", 2:"2026 OD Div 2",
                  3:"2026 OD Div 3",  4:"2026 OD Div 5"}
    rows = ""
    for t in TEAMS:
        num   = t["num"]
        color = div_colors[num]
        label = div_labels[num]
        tname = f"Hollywood {num}"
        entry = next(
            (s for s in all_standings.get(num, []) if tname in s["team"]),
            None
        )
        rows += (
            f'<tr style="background:#f0f4ff">'
            f'<td colspan="8" style="padding:8px 14px;font-size:11px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:.08em;color:{color}">'
            f'{label} — {tname}</td></tr>\n'
        )
        if entry:
            try:
                nrr_f   = float(entry["nrr"])
                nrr_col = "#27ae60" if nrr_f >= 0 else "#c0392b"
                nrr_str = f"+{nrr_f:.4f}" if nrr_f >= 0 else f"{nrr_f:.4f}"
            except ValueError:
                nrr_col, nrr_str = "#555", entry["nrr"]
            tie_nr = entry["tie"] + entry["nr"]
            rows += (
                f'<tr class="hw-row">'
                f'<td><strong>{entry["pos"]}</strong></td>'
                f'<td><strong>{tname}</strong></td>'
                f'<td>{entry["mat"]}</td><td>{entry["won"]}</td>'
                f'<td>{entry["lost"]}</td><td>{tie_nr}</td>'
                f'<td>{entry["pts"]}</td>'
                f'<td style="font-size:12px;color:{nrr_col}">{nrr_str}</td>'
                f'</tr>\n'
            )
        else:
            rows += (
                f'<tr class="hw-row"><td>–</td><td><strong>{tname}</strong></td>'
                f'<td colspan="6" style="color:#999">No data</td></tr>\n'
            )
    return rows


def build_ticker_items(all_data: dict) -> str:
    items = []

    def item(tag_cls, tag_text, text):
        return (
            f'<div class="ticker-item">'
            f'<span class="ticker-tag {tag_cls}">{tag_text}</span> {text}'
            f'</div>'
        )

    # Upcoming
    for t in TEAMS:
        for u in all_data[t["num"]]["upcoming"][:TICKER_UPCOMING_PER_TEAM]:
            venue_str = f' &bull; {u["venue"]}' if u["venue"] else ""
            items.append(item("upcoming", "Upcoming",
                f'{t["label"]} vs {u["opponent"]} &mdash; {u["date"]}{venue_str}'))

    # Recent results
    for t in TEAMS:
        for r in all_data[t["num"]]["results"][:TICKER_RESULTS_PER_TEAM]:
            oc = r["outcome"]
            if oc == "W":
                cls, verb = "win",  "beat"
            elif oc == "T":
                cls, verb = "tie",  "tied with"
            elif oc == "NR":
                cls, verb = "tie",  "vs"
            else:
                cls, verb = "loss", "lost to"
            margin = ""
            if "by" in r["result"].lower():
                margin = " by " + r["result"].lower().split("by", 1)[1].strip()
            short_date = " ".join(r["date"].split(",")[-1].strip().split()[:2]) \
                         if "," in r["date"] else r["date"]
            items.append(item(cls, "Result",
                f'{t["label"]} {verb} {r["opponent"]}{margin} &mdash; {short_date}'))

    # Player highlights — top bat + top bowl per team
    for t in TEAMS:
        num = t["num"]
        bat = all_data[num]["batting"]
        bwl = all_data[num]["bowling"]
        if bat:
            b = bat[0]
            items.append(item("highlight", "&#9733; Player",
                f'{b["name"]} ({t["label"]}) &mdash; {b["runs"]} runs'
                + (f', {b["fifties"]} fifties' if b["fifties"] else "")
                + f', avg {b["avg"]:.2f}'))
        if bwl:
            bw = bwl[0]
            items.append(item("highlight", "&#9733; Player",
                f'{bw["name"]} ({t["label"]}) &mdash; {bw["wkts"]} wkts'
                + (f' incl {bw["bbf"]}' if bw["bbf"] != "0/0" else "")
                + f', econ {bw["econ"]:.2f}'))

    # Standings snapshot
    for t in TEAMS:
        stgds = all_data[t["num"]]["standings"]
        entry = next((s for s in stgds if f'Hollywood {t["num"]}' in s["team"]), None)
        if entry and entry["won"] > 0:
            try:
                nrr_f = float(entry["nrr"])
                nrr_s = f'+{nrr_f:.2f}' if nrr_f >= 0 else f'{nrr_f:.2f}'
            except ValueError:
                nrr_s = entry["nrr"]
            suffix = {1:"st",2:"nd",3:"rd"}.get(entry["pos"], "th")
            items.append(item("highlight", "Standings",
                f'{t["label"]} sit {entry["pos"]}{suffix} in {t["division"]} &mdash; '
                f'{entry["won"]}W {entry["lost"]}L, {entry["pts"]} pts, NRR {nrr_s}'))

    # Double for seamless loop
    return ("\n        ".join(items) + "\n        " + "\n        ".join(items))


def replace_nth(text, pattern, replacement, n, flags=re.DOTALL):
    matches = list(re.finditer(pattern, text, flags))
    if len(matches) >= n:
        m = matches[n - 1]
        return text[:m.start()] + replacement + text[m.end():]
    return text


def update_html(html: str, all_data: dict) -> str:
    today = datetime.now().strftime("%B %-d, %Y")
    html  = re.sub(r'Live standings as of [^.]+\.', f'Live standings as of {today}.', html)

    # Standings rows
    new_rows = build_standings_rows({t["num"]: all_data[t["num"]]["standings"] for t in TEAMS})
    html = re.sub(
        r'(<tr style="background:#f0f4ff"><td colspan="8"[^>]*>2026 OD Div 1).*?'
        r'(</tr>\s*)$',
        new_rows,
        html, flags=re.DOTALL | re.MULTILINE, count=1
    )
    # Fallback direct replacement
    html = re.sub(
        r'<tr style="background:#f0f4ff">.*?2026 OD Div 1.*?</tr>.*?'
        r'(<tr style="background:#f0f4ff">.*?2026 OD Div 5.*?</tr>.*?</tr>)',
        new_rows,
        html, flags=re.DOTALL, count=1
    )

    # Team data arrays
    for t in TEAMS:
        num = t["num"]
        d   = all_data[num]

        def fmt_results(results):
            lines = []
            for r in results[:9]:
                margin = ""
                if "by" in r["result"].lower():
                    margin = "by " + r["result"].lower().split("by",1)[1].strip()
                outcome_str = (
                    f'W {margin}' if r["outcome"]=="W" and margin else
                    f'L {margin}' if r["outcome"]=="L" and margin else
                    r["outcome"]
                )
                opp   = r["opponent"].replace("'", "")
                venue = r["venue"].replace("'", "")
                lines.append(
                    f"      {{date:'{r['date']}',opp:'{opp}',venue:'{venue}',"
                    f"hw1:'{r['hw_score']}',opp_score:'{r['opp_score']}',"
                    f"result:'{outcome_str.replace(chr(39),'')}'}}"
                )
            return "[\n" + ",\n".join(lines) + "\n    ]"

        def fmt_batting(stats):
            lines = []
            for b in stats[:10]:
                lines.append(
                    f"      {{rank:{b['rank']},name:'{b['name'].replace(chr(39),'')}'"
                    f",mat:{b['mat']},inns:{b['inns']},no:{b['no']},runs:{b['runs']}"
                    f",balls:{b['balls']},fours:{b['fours']},sixes:{b['sixes']}"
                    f",fifties:{b['fifties']},hundreds:{b['hundreds']},hs:{b['hs']}"
                    f",sr:{b['sr']},avg:{b['avg']}}}"
                )
            return "[\n" + ",\n".join(lines) + "\n    ]"

        def fmt_bowling(stats):
            lines = []
            for bw in stats[:8]:
                lines.append(
                    f"      {{rank:{bw['rank']},name:'{bw['name'].replace(chr(39),'')}'"
                    f",mat:{bw['mat']},overs:{bw['overs']},mdns:{bw['mdns']}"
                    f",runs:{bw['runs']},wkts:{bw['wkts']},bbf:'{bw['bbf']}'"
                    f",econ:{bw['econ']},avg:{bw['avg']},sr:{bw['sr']}}}"
                )
            return "[\n" + ",\n".join(lines) + "\n    ]"

        if d["results"]:
            html = replace_nth(html, r'results:\[.*?\](?=,\s*\n\s*upcoming:)',
                               f'results:{fmt_results(d["results"])}', num)
        if d["batting"]:
            html = replace_nth(html, r'batting:\[.*?\](?=,\s*\n\s*bowling:)',
                               f'batting:{fmt_batting(d["batting"])}', num)
        if d["bowling"]:
            html = replace_nth(html, r'bowling:\[.*?\](?=,\s*\n\s*fielding:)',
                               f'bowling:{fmt_bowling(d["bowling"])}', num)

    # Ticker
    new_ticker = build_ticker_items(all_data)
    html = re.sub(
        r'(<div class="ticker-inner"[^>]*>)\s*.*?(\s*</div>\s*</div>\s*</div>\s*\n\s*<div class="stats-strip">)',
        rf'\g<1>\n        {new_ticker}\n      \g<2>',
        html, flags=re.DOTALL, count=1
    )

    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HCC weekly site updater")
    parser.add_argument("--input",   default="hollywoodcc.html")
    parser.add_argument("--output",  default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright not installed. Run: pip install playwright && playwright install chromium")
        return

    all_data = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",             # required on GitHub Actions
                "--disable-dev-shm-usage",  # avoids /dev/shm issues in containers
                "--disable-gpu",
            ]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        for t in TEAMS:
            num = t["num"]
            log.info(f"Scraping {t['name']} ({t['division']}) ...")

            standings = scrape_points_table(page, t)
            results   = scrape_team_results(page, t)
            upcoming  = scrape_team_schedule(page, t)
            batting   = scrape_batting(page, t)
            bowling   = scrape_bowling(page, t)

            all_data[num] = {
                "standings": standings,
                "results":   results,
                "upcoming":  upcoming,
                "batting":   batting,
                "bowling":   bowling,
            }

        browser.close()

    html     = input_path.read_text(encoding="utf-8")
    new_html = update_html(html, all_data)

    if args.dry_run:
        log.info("Dry run — no file written. Summary:")
        for t in TEAMS:
            num = t["num"]
            d   = all_data[num]
            w   = sum(1 for r in d["results"] if r["outcome"] == "W")
            l   = sum(1 for r in d["results"] if r["outcome"] == "L")
            bat = d["batting"][0]["name"] + f' {d["batting"][0]["runs"]}r' if d["batting"] else "–"
            bwl = d["bowling"][0]["name"] + f' {d["bowling"][0]["wkts"]}w' if d["bowling"] else "–"
            print(f"  {t['name']}: {w}W {l}L | {len(d['upcoming'])} upcoming | "
                  f"Top bat: {bat} | Top bowl: {bwl}")
    else:
        output_path.write_text(new_html, encoding="utf-8")
        log.info(f"✓ Written: {output_path}")
        log.info(f"✓ Done — {datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()

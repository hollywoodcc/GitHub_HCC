# Hollywood Cricket Club — Automated Site Updater

Automatically scrapes all 4 Hollywood team pages from **cricclubs.com/SCCA**
every Monday morning and updates `hollywoodcc.html` with the latest:

- Match results & upcoming fixtures
- Batting & bowling statistics
- League standings & NRR
- Scrolling ticker content
- "Last updated" date

---

## Files

| File | Purpose |
|------|---------|
| `scraper.py` | Main scraper — run manually or via GitHub Actions |
| `.github/workflows/weekly-update.yml` | GitHub Actions schedule (runs every Monday) |
| `hollywoodcc.html` | Your website file |

---

## One-time setup (30 minutes)

### Step 1 — Create a GitHub account
Go to **github.com** → Sign up (free)

### Step 2 — Create a new repository
1. Click **+** → **New repository**
2. Name it `hollywoodcc-website`
3. Set it to **Public**
4. Click **Create repository**

### Step 3 — Upload your files
Upload these files to the root of your new repository:
- `hollywoodcc.html`
- `scraper.py`
- `.github/workflows/weekly-update.yml`  ← keep this exact folder path

### Step 4 — Enable GitHub Pages
1. Go to your repo → **Settings** → **Pages**
2. Under *Source*, select **Deploy from a branch**
3. Branch: **main**, Folder: **/ (root)**
4. Click **Save**
5. Your site will be live at `https://yourusername.github.io/hollywoodcc-website`

### Step 5 — Test the workflow manually
1. Go to your repo → **Actions** tab
2. Click **Weekly HCC Site Update** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch it run — takes about 3-4 minutes
5. Check your live site to confirm it updated

---

## Weekly automation
Once set up, the workflow runs **every Monday at 6am PDT** automatically.
You don't need to do anything.

To change the day/time, edit line 6 of `weekly-update.yml`:
```yaml
- cron: "0 14 * * 1"   # Monday 6am PDT
```
Use [crontab.guru](https://crontab.guru) to generate a different schedule.

---

## Running manually (local)

### Install dependencies
```bash
pip install requests beautifulsoup4 playwright
playwright install chromium
```

### Run the updater
```bash
# Update hollywoodcc.html in place
python scraper.py

# Specify a different file
python scraper.py --input path/to/hollywoodcc.html

# Preview changes without writing
python scraper.py --dry-run
```

---

## Uploading to GoDaddy after each run

When the GitHub Action runs, it commits the updated `hollywoodcc.html` back
to your repo. To push it to GoDaddy:

1. Download `hollywoodcc.html` from your GitHub repo
2. Log in to GoDaddy → **cPanel** → **File Manager**
3. Open **public_html**
4. Delete the old `index.html`
5. Upload the new file and rename to `index.html`

> **Tip:** If you host on GitHub Pages instead of GoDaddy, step 4 is
> automatic — the site updates itself the moment the Action commits.

---

## What gets updated

| Section | Fields updated |
|---------|---------------|
| Home standings table | Position, P/W/L/T, Points, NRR |
| Team detail pages | Results, batting stats, bowling stats |
| Upcoming fixtures | Next 2 fixtures per team |
| Scrolling ticker | All results, upcoming games, player highlights |
| Date stamp | "Live standings as of …" |

---

## Troubleshooting

**Action fails with "playwright not found"**
→ Ensure `playwright install --with-deps chromium` step ran. Check the
Actions log for errors.

**No changes committed**
→ CricClubs data may not have changed since last run. This is normal
mid-week.

**Site not updating on GoDaddy**
→ Remember to manually download from GitHub and re-upload to cPanel
(or switch to GitHub Pages hosting for fully automatic updates).

**Scraper gets wrong data**
→ CricClubs may have changed their HTML structure. Open an issue or
come back to Claude and say "fix the scraper" — paste the error message.

---

## Support
Built with ❤️ for Hollywood Cricket Club — founded 1932, Griffith Park, LA.

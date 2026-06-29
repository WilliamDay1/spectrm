#!/usr/bin/env python3
"""
fetch_manifesto.py - Updates manifesto tracker. Runs monthly.

Full Fact blocks automated scraping, so this script instead checks
the Full Fact sitemap/RSS for any updates to tracked pages, and
updates the 'updated' timestamp. Manual status updates are still
needed when Full Fact changes a verdict - this script flags which
pledges have been recently touched on the Full Fact site.
"""
import json, os, sys, re, urllib.request
from datetime import datetime, date

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA_FILE = os.path.join(REPO_ROOT, 'data', 'manifesto.json')

# Full Fact RSS feed for government tracker updates
FF_RSS = 'https://fullfact.org/category/government-tracker/feed/'

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Spectrm/1.0 data journalism'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  WARN: {e}", file=sys.stderr)
        return ''

def main():
    print(f"fetch_manifesto.py — {datetime.now().isoformat()}")

    try:
        with open(DATA_FILE) as f:
            current = json.load(f)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    pledges = current.get('pledges', [])
    print(f"Loaded {len(pledges)} pledges from {DATA_FILE}")

    # Try to fetch Full Fact RSS to see what's been recently updated
    print("Checking Full Fact RSS for recent updates...")
    rss = fetch(FF_RSS)
    recently_updated = []

    if rss:
        # Extract titles from RSS
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', rss)
        titles += re.findall(r'<title>(.*?)</title>', rss)
        recently_updated = [t.strip().lower() for t in titles if len(t.strip()) > 10]
        print(f"  Found {len(recently_updated)} recent Full Fact updates")
        for t in recently_updated[:5]:
            print(f"    - {t[:70]}")
    else:
        print("  Could not reach Full Fact RSS — updating timestamp only")

    # Flag pledges that appear in recent Full Fact updates
    flagged = 0
    for pledge in pledges:
        pledge_words = set(pledge['pledge'].lower().split())
        for title in recently_updated:
            title_words = set(title.split())
            # If 4+ words overlap, likely the same pledge
            overlap = len(pledge_words & title_words)
            if overlap >= 4:
                pledge['_recently_updated_on_fullfact'] = True
                flagged += 1
                print(f"  FLAGGED (check manually): {pledge['pledge'][:60]}")
                break

    # Recount statuses
    status_keys = ['achieved','on_track','in_progress','off_track','not_kept','unclear','wait_and_see']
    counts = {k: 0 for k in status_keys}
    for p in pledges:
        s = p.get('status','wait_and_see')
        if s in counts:
            counts[s] += 1

    current['summary'] = {'total': len(pledges), **counts}
    current['pledges'] = pledges
    current['_meta']['updated'] = date.today().isoformat()
    current['_meta']['note'] = (
        f"Auto-checked {date.today().isoformat()}. "
        f"{flagged} pledge(s) may need manual review — check Full Fact. "
        "Full Fact blocks scraping so status changes require manual update."
    )

    with open(DATA_FILE, 'w') as f:
        json.dump(current, f, indent=2)

    print(f"\nDone. Summary: {counts}")
    print(f"{flagged} pledge(s) flagged for manual review.")
    print("NOTE: To update a pledge status, edit data/manifesto.json and push to GitHub.")

if __name__ == '__main__':
    main()

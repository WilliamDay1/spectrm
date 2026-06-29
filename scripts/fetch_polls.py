#!/usr/bin/env python3
"""
fetch_polls.py - Updates polling averages. Runs weekly via GitHub Actions.
Parses the Wikipedia UK polling table which is community-maintained and reliable.
"""
import json, os, sys, re, urllib.request
from datetime import datetime, date

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA_FILE = os.path.join(REPO_ROOT, 'data', 'polls.json')

WIKI_URL = 'https://en.wikipedia.org/wiki/Opinion_polling_for_the_next_United_Kingdom_general_election'

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Spectrm/1.0 data journalism'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  WARN: {e}", file=sys.stderr)
        return ''

def parse_polls(html):
    """Extract recent poll rows from Wikipedia table."""
    polls = []
    # Find rows containing poll percentages - look for patterns like "26.3" in table cells
    # Wikipedia tables use | as cell separators in wikitext but we're parsing HTML
    # Find all <tr> rows that contain percentage-like numbers
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    
    # Find the header row to map columns
    col_map = {}
    party_names = {
        'con': ['conservative', 'con'],
        'lab': ['labour', 'lab'],
        'lib': ['liberal democrat', 'lib dem', 'ld'],
        'ref': ['reform', 'reform uk'],
        'grn': ['green'],
        'snp': ['snp'],
    }
    
    for row in rows[:10]:
        cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
        clean = [re.sub(r'<[^>]+>', '', c).strip().lower() for c in cells]
        text = ' '.join(clean)
        if 'labour' in text and 'conservative' in text:
            for party, names in party_names.items():
                for i, cell in enumerate(clean):
                    if any(n in cell for n in names):
                        col_map[party] = i
                        break
            break
    
    if not col_map:
        print("  Could not find header row", file=sys.stderr)
        return []
    
    print(f"  Column map: {col_map}")
    
    for row in rows:
        cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
        clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        
        poll = {}
        for party, idx in col_map.items():
            if idx < len(clean):
                val = re.sub(r'[^0-9.]', '', clean[idx])
                try:
                    v = float(val)
                    if 1 < v < 60:  # sanity check — valid poll %
                        poll[party] = round(v, 1)
                except ValueError:
                    pass
        
        # Valid row needs at least Lab + Con + Ref
        if all(p in poll for p in ['lab', 'con', 'ref']):
            poll['date_str'] = clean[0] if clean else ''
            polls.append(poll)
    
    return polls[:20]

def compute_avg(polls, n=7):
    recent = polls[:n]
    if not recent:
        return {}
    avg = {}
    for p in ['lab', 'con', 'lib', 'ref', 'grn', 'snp']:
        vals = [row[p] for row in recent if p in row]
        if vals:
            avg[p] = round(sum(vals) / len(vals), 1)
    return avg

def main():
    print(f"fetch_polls.py — {datetime.now().isoformat()}")
    
    try:
        with open(DATA_FILE) as f:
            current = json.load(f)
    except Exception as e:
        print(f"ERROR loading {DATA_FILE}: {e}", file=sys.stderr)
        sys.exit(1)
    
    print("Fetching Wikipedia polling table...")
    html = fetch(WIKI_URL)
    
    if not html:
        print("Could not fetch Wikipedia — keeping existing data")
        sys.exit(0)
    
    polls = parse_polls(html)
    print(f"  Parsed {len(polls)} poll rows")
    
    if polls:
        avg = compute_avg(polls)
        print(f"  7-poll average: {avg}")
        if avg:
            current['average'] = {'date': date.today().isoformat(), **avg}
            # Update last month in history
            h = current.get('monthly_history', {})
            today_label = datetime.now().strftime('%b %y')
            labels = h.get('labels', [])
            if labels and labels[-1] == today_label:
                for p in ['ref','lab','con','grn','lib']:
                    if p in h and h[p] and p in avg:
                        h[p][-1] = avg[p]
                print(f"  Updated current month: {today_label}")
            elif labels:
                for p in ['ref','lab','con','grn','lib']:
                    h.setdefault(p, []).append(avg.get(p, 0))
                labels.append(today_label)
                h['labels'] = labels
                print(f"  Appended new month: {today_label}")
            current['monthly_history'] = h
    else:
        print("  No polls parsed — keeping existing averages")
    
    current.setdefault('_meta', {})['updated'] = date.today().isoformat()
    with open(DATA_FILE, 'w') as f:
        json.dump(current, f, indent=2)
    print(f"Saved {DATA_FILE}")

if __name__ == '__main__':
    main()

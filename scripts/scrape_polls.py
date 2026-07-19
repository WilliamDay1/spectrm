#!/usr/bin/env python3
"""
Scrapes UK VI polls from Wikipedia.
Column order from debug: Date(s)=0, Pollster=1, Client=2, Area=3, Sample=4, Lab=5, Con=6, Ref=7, LD=8, Grn=9
"""
import json, re, sys
from datetime import datetime
from collections import defaultdict
import urllib.request, urllib.parse

MONTH_MAP = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
             'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
MON_ABBR = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

POLLSTER_SRCS = {
    'YouGov':'yougov.com','More in Common':'moreincommon.org.uk',
    'Opinium':'opinium.com','Survation':'survation.com',
    'Savanta':'savanta.com','Ipsos':'ipsos.com',
    'JL Partners':'jlpartners.co.uk','Find Out Now':'findoutnow.co.uk',
    'Ashcroft':'lordashcroftpolls.com','Redfield':'redfieldandwiltonstrategies.com',
    'BMG':'bmgresearch.co.uk','Deltapoll':'deltapoll.co.uk',
    'Techne':'techneuk.co.uk','Norstat':'norstat.co.uk',
}
KNOWN_POLLSTERS = list(POLLSTER_SRCS.keys())

LEADER_MAP = {
    'Andy Burnham':'lab','Keir Starmer':'lab','Kemi Badenoch':'con',
    'Nigel Farage':'ref','Ed Davey':'lib','Zack Polanski':'grn','Angela Rayner':'lab',
}

# HARDCODED from debug output — Wikipedia VI table columns:
# Date(s) conducted=0, Pollster=1, Client=2, Area=3, Sample size=4,
# Lab=5, Con=6, Ref=7, LD=8, Grn=9, SNP=10, PC=11, RB=12, Others=13, Lead=14
FIXED_COL = {'date':0,'pollster':1,'n':4,'lab':5,'con':6,'ref':7,'lib':8,'grn':9}

def fetch_wiki(page):
    url = "https://en.wikipedia.org/w/api.php"
    params = urllib.parse.urlencode({
        "action": "parse",
        "page": page,
        "prop": "text",
        "format": "json",
        "disablelimitreport": "1"
    })
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"User-Agent": "Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode('utf-8'))
    return data.get("parse", {}).get("text", {}).get("*", "")

# Override with requests if available
try:
    import requests
    def fetch_wiki(page):
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action":"parse","page":page,"prop":"text","format":"json","disablelimitreport":"1"},
            headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"},
            timeout=30
        )
        r.raise_for_status()
        return r.json().get("parse", {}).get("text", {}).get("*", "")
except ImportError:
    pass

def st(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'&[a-zA-Z0-9]+;', ' ', s)
    s = re.sub(r'&#\d+;', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def pct(s):
    s = st(s).replace('%', '').strip()
    m = re.search(r'(\d+(?:\.\d+)?)', s)
    try: return round(float(m.group(1))) if m else None
    except: return None

def parse_date(s, yr=None):
    s = st(s).replace('–', '-')
    m = re.search(r'(\d{1,2})(?:\s*-\s*\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})', s)
    if m:
        d, mo, y = int(m.group(1)), MONTH_MAP.get(m.group(2).lower()[:3], 0), int(m.group(3))
        if mo and y >= 2024: return y*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(y)[2:]}"
    m = re.search(r'(\d{1,2})(?:\s*-\s*\d{1,2})?\s+([A-Za-z]+)', s)
    if m and yr:
        d, mo = int(m.group(1)), MONTH_MAP.get(m.group(2).lower()[:3], 0)
        if mo: return yr*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(yr)[2:]}"
    m = re.search(r'([A-Za-z]+)\s+(\d{4})', s)
    if m:
        mo, y = MONTH_MAP.get(m.group(1).lower()[:3], 0), int(m.group(2))
        if mo and y >= 2024: return y*10000+mo*100+1, f"{MON_ABBR[mo]} {str(y)[2:]}"
    return None, None

def row_cells(row_html):
    return [st(m.group(1)) for m in re.finditer(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL)]

def parse_vi(html):
    all_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    print(f"  Total <tr> rows: {len(all_rows)}", file=sys.stderr)

    col = FIXED_COL.copy()
    print(f"  Using hardcoded cols: {col}", file=sys.stderr)

    polls = []
    cur_yr = None

    for r in all_rows:
        cells = row_cells(r)
        if not cells: continue
        raw = ' '.join(cells)

        # Detect year header rows
        ym = re.match(r'^(202\d)\s*$', raw.strip())
        if ym:
            cur_yr = int(ym.group(1))
            print(f"  Year: {cur_yr}", file=sys.stderr)
            continue

        # Must have % signs to be a data row
        if '%' not in raw: continue
        if len(cells) < 9: continue

        # Extract values using fixed column positions
        def gc(k):
            idx = col.get(k)
            if idx is not None and idx < len(cells):
                return pct(cells[idx])
            return None

        lab, con, ref, lib, grn = gc('lab'), gc('con'), gc('ref'), gc('lib'), gc('grn')

        if not all(v is not None for v in [ref, lab, con, lib, grn]):
            continue
        if not (5<=ref<=50 and 5<=lab<=55 and 5<=con<=50 and 3<=lib<=30 and 3<=grn<=30):
            continue

        # Date
        dtxt = cells[col['date']] if col['date'] < len(cells) else ''
        sk, ds = parse_date(dtxt, cur_yr)
        if not sk:
            for c in cells:
                sk, ds = parse_date(c, cur_yr)
                if sk: break
        if not sk: continue

        # Sample size
        n = None
        n_idx = col.get('n')
        if n_idx is not None and n_idx < len(cells):
            raw_n = re.sub(r'[^0-9]', '', cells[n_idx])
            if raw_n and 500 <= int(raw_n) <= 5000:
                n = int(raw_n)
        if not n:
            for c in cells:
                raw_n = re.sub(r'[^0-9]', '', c)
                if raw_n and 500 <= int(raw_n) <= 5000:
                    n = int(raw_n); break
        if not n: continue

        # Pollster
        pollster = None
        for ci in range(min(4, len(cells))):
            clean = re.sub(r'\s*\[?\d+\]?$', '', cells[ci]).strip()
            for known in KNOWN_POLLSTERS:
                if known.lower() in clean.lower():
                    pollster = known; break
            if pollster: break
        if not pollster:
            raw_p = re.sub(r'\s*\[?\d+\]?$', '', cells[col.get('pollster', 1)] if col.get('pollster', 1) < len(cells) else '').strip()
            if 2 < len(raw_p) < 35 and raw_p[0].isupper():
                pollster = raw_p
            else:
                continue

        polls.append({
            'pollster': pollster, 'date': ds, 'sort_key': sk, 'n': n,
            'ref': ref, 'lab': lab, 'con': con, 'lib': lib, 'grn': grn,
            'client': '', 'src': POLLSTER_SRCS.get(pollster, '')
        })

    print(f"  Raw polls found: {len(polls)}", file=sys.stderr)
    seen, unique = set(), []
    for p in sorted(polls, key=lambda x: -x['sort_key']):
        k = (p['pollster'], p['sort_key'])
        if k not in seen:
            seen.add(k); unique.append(p)
    return unique[:50]

def build_monthly(polls):
    bm = defaultdict(list)
    for p in polls: bm[p['sort_key'] // 100].append(p)
    labels, ra, la, ca, ga, lia = [], [], [], [], [], []
    avg = lambda lst, k: round(sum(x[k] for x in lst) / len(lst), 1)
    for ym in sorted(bm):
        mo = ym % 100; g = bm[ym]
        labels.append(f"{MON_ABBR[mo]} {str(ym//100)[2:]}")
        ra.append(avg(g,'ref')); la.append(avg(g,'lab')); ca.append(avg(g,'con'))
        ga.append(avg(g,'grn')); lia.append(avg(g,'lib'))
    return {'labels': labels, 'ref': ra, 'lab': la, 'con': ca, 'grn': ga, 'lib': lia}

def parse_leaders(html):
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    results = {}; cur = None
    for h in re.findall(r'<h[2-4][^>]*>(.*?)</h[2-4]>', html, re.DOTALL):
        ht = st(h)
        for name in LEADER_MAP:
            if name.split()[-1] in ht and name.split()[0] in ht: cur = name
    for r in rows:
        cells = row_cells(r); full = ' '.join(cells)
        for name in LEADER_MAP:
            if name.split()[-1] in full and len(full) < 100: cur = name; break
        if not cur or len(cells) < 3: continue
        sk, ds = None, None
        for c in cells:
            sk, ds = parse_date(c)
            if sk and sk > 20240700: break
        if not sk: continue
        pollster = ''
        for c in cells:
            for known in KNOWN_POLLSTERS:
                if known.lower() in c.lower(): pollster = known; break
            if pollster: break
        nums = [v for c in cells if (v := pct(c)) is not None and 10 <= v <= 80]
        if len(nums) < 2: continue
        ap, di = nums[0], nums[1]
        if ap + di > 130: continue
        if cur not in results or sk > results[cur]['sk']:
            results[cur] = {'sk': sk, 'date': ds, 'pollster': pollster, 'approve': ap, 'disapprove': di}
    out = []
    for name, r in results.items():
        src = f"YouGov · {r['date']}" if r['pollster'] == 'YouGov' else f"{r['pollster']} · {r['date']}"
        out.append({'name': name, 'approve': r['approve'], 'disapprove': r['disapprove'],
                    'net': r['approve'] - r['disapprove'], 'src': src})
        print(f"  {name}: {r['approve']}%/{r['disapprove']}% ({src})", file=sys.stderr)
    return out

def main():
    VI = "Opinion_polling_for_the_next_United_Kingdom_general_election"
    LA = "Leadership_approval_opinion_polling_for_the_next_United_Kingdom_general_election"
    print("Fetching VI...", file=sys.stderr)
    vi_html = fetch_wiki(VI)
    print(f"  HTML: {len(vi_html)} chars", file=sys.stderr)
    polls = parse_vi(vi_html)
    print(f"  Unique polls: {len(polls)}", file=sys.stderr)
    if not polls:
        print("ERROR: no polls", file=sys.stderr); sys.exit(1)
    for p in polls[:3]:
        print(f"  {p['pollster']} {p['date']}: Ref{p['ref']} Lab{p['lab']} Con{p['con']} n={p['n']}", file=sys.stderr)
    monthly = build_monthly(polls)
    print(f"  Monthly: {monthly['labels']}", file=sys.stderr)
    print("Fetching leaders...", file=sys.stderr)
    try:
        la_html = fetch_wiki(LA)
        leaders = parse_leaders(la_html)
        print(f"  {len(leaders)} leaders", file=sys.stderr)
    except Exception as e:
        print(f"  WARNING: {e}", file=sys.stderr); leaders = []
    for p in polls: p.pop('sort_key', None)
    print(json.dumps({
        'generated': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'monthly_history': monthly,
        'recent_polls': polls[:10],
        'leader_approval': leaders,
    }, indent=2))
    print(f"\nDone: {len(polls)} polls · {len(monthly['labels'])} months · {len(leaders)} leaders", file=sys.stderr)

if __name__ == '__main__': main()

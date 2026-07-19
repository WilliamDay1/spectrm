#!/usr/bin/env python3
"""
Scrapes UK VI polls from Wikipedia.
Uses the Wikipedia API to get parsed HTML, then extracts table data.
"""
import json, re, sys
from datetime import datetime
from collections import defaultdict
import urllib.request
import urllib.parse

def fetch(url, params=None):
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url,
        headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8')

try:
    import requests
    def fetch(url, params=None):
        r = requests.get(url, params=params,
            headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"},
            timeout=30)
        r.raise_for_status()
        return r.text
except ImportError:
    pass

MONTH_MAP = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
             'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
MON_ABBR  = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

KNOWN_POLLSTERS = [
    'YouGov','More in Common','Opinium','Survation','Savanta',
    'Ipsos','JL Partners','Find Out Now','Ashcroft','Redfield',
    'BMG','Deltapoll','Techne','Norstat','Panelbase','Number Cruncher',
]
POLLSTER_SRCS = {
    'YouGov':'yougov.com','More in Common':'moreincommon.org.uk',
    'Opinium':'opinium.com','Survation':'survation.com',
    'Savanta':'savanta.com','Ipsos':'ipsos.com',
    'JL Partners':'jlpartners.co.uk','Find Out Now':'findoutnow.co.uk',
    'Ashcroft':'lordashcroftpolls.com','Redfield':'redfieldandwiltonstrategies.com',
    'BMG':'bmgresearch.co.uk','Deltapoll':'deltapoll.co.uk',
    'Techne':'techneuk.co.uk','Norstat':'norstat.co.uk',
}

LEADER_MAP = {
    'Andy Burnham':  'lab',
    'Keir Starmer':  'lab',
    'Kemi Badenoch': 'con',
    'Nigel Farage':  'ref',
    'Ed Davey':      'lib',
    'Zack Polanski': 'grn',
    'Angela Rayner': 'lab',
}

def strip_tags(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def clean_num(s):
    s = re.sub(r'[^0-9.]', '', strip_tags(s))
    try: return round(float(s))
    except: return None

def parse_date(s):
    s = strip_tags(s).replace('–','-').replace('—','-')
    m = re.search(r'(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})', s)
    if m:
        d, mon, yr = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        mo = MONTH_MAP.get(mon, 0)
        if mo and yr >= 2024:
            return yr*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(yr)[2:]}"
    m = re.search(r'([A-Za-z]+)\s+(\d{4})', s)
    if m:
        mon, yr = m.group(1).lower()[:3], int(m.group(2))
        mo = MONTH_MAP.get(mon, 0)
        if mo and yr >= 2024:
            return yr*10000+mo*100+1, f"{MON_ABBR[mo]} {str(yr)[2:]}"
    return None, None

def get_wiki_parsed_html(page):
    """Get Wikipedia page as parsed HTML via the API."""
    data = json.loads(fetch("https://en.wikipedia.org/w/api.php", {
        "action": "parse",
        "page": page,
        "prop": "text",
        "format": "json",
        "disablelimitreport": "1",
    }))
    return data.get("parse", {}).get("text", {}).get("*", "")

def extract_table_rows(html):
    """Extract all table rows as lists of cell text strings."""
    rows = []
    for table in re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL):
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL):
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
            if cells:
                rows.append([strip_tags(c) for c in cells])
    return rows

def parse_vi_polls(html):
    rows = extract_table_rows(html)
    print(f"  Total table rows found: {len(rows)}", file=sys.stderr)

    polls = []
    for cells in rows:
        if len(cells) < 6:
            continue

        # Skip obvious header rows
        joined = ' '.join(cells[:4]).lower()
        if any(h in joined for h in ['pollster','firm','fieldwork','date','poll','client']):
            continue

        # Find pollster in first 3 cells
        pollster = None
        for ci in range(min(3, len(cells))):
            for known in KNOWN_POLLSTERS:
                if known.lower() in cells[ci].lower():
                    pollster = known; break
            if pollster: break
        if not pollster:
            raw = cells[0].strip()
            if 2 < len(raw) < 35 and raw[0].isupper():
                pollster = raw
            else:
                continue

        # Find date post July 2024
        sort_key, date_str = None, None
        for c in cells:
            sk, ds = parse_date(c)
            if sk and sk > 20240704:
                sort_key, date_str = sk, ds; break
        if not sort_key:
            continue

        # Sample size 500-5000 (exclude MRP polls)
        n = None
        for c in cells:
            raw = re.sub(r'[^0-9]', '', c)
            if raw and 500 <= int(raw) <= 5000:
                n = int(raw); break
        if not n:
            continue

        # Get all numbers between 3 and 55
        nums = []
        for c in cells:
            v = clean_num(c)
            if v is not None and 3 <= v <= 55:
                nums.append(v)

        # Find 5 consecutive values summing 85-105
        best = None
        for i in range(len(nums)):
            sub = nums[i:i+5]
            if len(sub) == 5 and 85 <= sum(sub) <= 105:
                best = sub; break
        if not best:
            continue

        ref, lab, con, lib, grn = best
        polls.append({
            'pollster': pollster,
            'client': cells[1][:40] if len(cells)>1 else '',
            'date': date_str,
            'sort_key': sort_key,
            'n': n,
            'ref': ref, 'lab': lab, 'con': con, 'lib': lib, 'grn': grn,
            'src': POLLSTER_SRCS.get(pollster, ''),
        })

    # Deduplicate newest-first
    seen, unique = set(), []
    for p in sorted(polls, key=lambda x: -x['sort_key']):
        k = (p['pollster'], p['sort_key'])
        if k not in seen:
            seen.add(k); unique.append(p)

    return unique[:50]

def build_monthly_history(polls):
    by_month = defaultdict(list)
    for p in polls:
        by_month[p['sort_key']//100].append(p)
    labels,ref_a,lab_a,con_a,grn_a,lib_a=[],[],[],[],[],[]
    def avg(lst,k): return round(sum(x[k] for x in lst)/len(lst),1)
    for ym in sorted(by_month):
        mo=ym%100
        labels.append(f"{MON_ABBR[mo]} {str(ym//100)[2:]}")
        g=by_month[ym]
        ref_a.append(avg(g,'ref')); lab_a.append(avg(g,'lab'))
        con_a.append(avg(g,'con')); grn_a.append(avg(g,'grn'))
        lib_a.append(avg(g,'lib'))
    return {'labels':labels,'ref':ref_a,'lab':lab_a,'con':con_a,'grn':grn_a,'lib':lib_a}

def parse_leader_approval(html):
    rows = extract_table_rows(html)
    results = {}
    current_leader = None

    # Also scan for headings in the HTML
    headings = re.findall(r'<h[23][^>]*>.*?([A-Z][a-z]+ [A-Z][a-z]+).*?</h[23]>', html, re.DOTALL)

    for cells in rows:
        if not cells: continue

        # Check if any cell is a leader name
        for name in LEADER_MAP:
            last = name.split()[-1]
            if any(last in c for c in cells[:3]) and any(name.split()[0] in c for c in cells[:3]):
                current_leader = name; break

        if not current_leader or len(cells) < 3:
            continue

        sort_key, date_str = None, None
        for c in cells:
            sk, ds = parse_date(c)
            if sk and sk > 20240700:
                sort_key, date_str = sk, ds; break
        if not sort_key:
            continue

        pollster = ''
        for c in cells:
            for known in KNOWN_POLLSTERS:
                if known.lower() in c.lower():
                    pollster = known; break
            if pollster: break

        nums = [v for c in cells if (v:=clean_num(c)) is not None and 10<=v<=80]
        if len(nums) < 2: continue

        approve, disapprove = nums[0], nums[1]
        if approve + disapprove > 130: continue

        if current_leader not in results or sort_key > results[current_leader]['sort_key']:
            results[current_leader] = {
                'sort_key':sort_key,'date':date_str,'pollster':pollster,
                'approve':approve,'disapprove':disapprove,
            }

    output = []
    for name, r in results.items():
        src = f"YouGov · {r['date']}" if r['pollster']=='YouGov' else f"{r['pollster']} · {r['date']}"
        output.append({'name':name,'approve':r['approve'],'disapprove':r['disapprove'],
                       'net':r['approve']-r['disapprove'],'src':src})
        print(f"  {name}: {r['approve']}%/{r['disapprove']}% ({src})", file=sys.stderr)
    return output

def main():
    VI_PAGE = "Opinion_polling_for_the_next_United_Kingdom_general_election"
    LA_PAGE = "Leadership_approval_opinion_polling_for_the_next_United_Kingdom_general_election"

    print("Fetching VI polls HTML...", file=sys.stderr)
    vi_html = get_wiki_parsed_html(VI_PAGE)
    print(f"  HTML length: {len(vi_html)} chars", file=sys.stderr)

    polls = parse_vi_polls(vi_html)
    print(f"  {len(polls)} polls parsed", file=sys.stderr)

    if polls:
        for p in polls[:3]:
            print(f"  Sample: {p['pollster']} {p['date']} Ref{p['ref']} Lab{p['lab']} Con{p['con']} n={p['n']}", file=sys.stderr)
    else:
        print("ERROR: no polls parsed", file=sys.stderr)
        sys.exit(1)

    monthly = build_monthly_history(polls)
    print(f"  Monthly labels: {monthly['labels']}", file=sys.stderr)

    print("Fetching leader approval...", file=sys.stderr)
    try:
        la_html = get_wiki_parsed_html(LA_PAGE)
        leaders = parse_leader_approval(la_html)
        print(f"  {len(leaders)} leaders", file=sys.stderr)
    except Exception as e:
        print(f"  WARNING: {e}", file=sys.stderr)
        leaders = []

    for p in polls: p.pop('sort_key', None)

    print(json.dumps({
        'generated': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'monthly_history': monthly,
        'recent_polls': polls[:10],
        'leader_approval': leaders,
    }, indent=2))

    print(f"\nDone: {len(polls)} polls · {len(monthly['labels'])} months · {len(leaders)} leaders", file=sys.stderr)

if __name__ == '__main__':
    main()

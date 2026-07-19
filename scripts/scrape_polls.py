#!/usr/bin/env python3
"""
Scrapes UK VI polls from Wikipedia.
Uses a direct regex approach on the raw HTML rather than table parsing.
"""
import json, re, sys
from datetime import datetime
from collections import defaultdict
import urllib.request, urllib.parse

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
    'Freshwater','Omnisis','Focaldata','Brains',
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
    'Andy Burnham':'lab','Keir Starmer':'lab','Kemi Badenoch':'con',
    'Nigel Farage':'ref','Ed Davey':'lib','Zack Polanski':'grn','Angela Rayner':'lab',
}

def strip_tags(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'&#?[a-zA-Z0-9]+;', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def clean_pct(s):
    s = strip_tags(s).replace('%','').replace('−','-').strip()
    s = re.sub(r'[^0-9.]', '', s)
    try: return round(float(s))
    except: return None

def parse_date(s, default_year=None):
    s = strip_tags(s).replace('–','-').replace('—','-')
    # Full date with year
    m = re.search(r'(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})', s)
    if m:
        d, mon, yr = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        mo = MONTH_MAP.get(mon, 0)
        if mo and yr >= 2024:
            return yr*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(yr)[2:]}"
    # Date without year — try default_year
    m = re.search(r'(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s+([A-Za-z]+)', s)
    if m and default_year:
        d, mon = int(m.group(1)), m.group(2).lower()[:3]
        mo = MONTH_MAP.get(mon, 0)
        if mo:
            yr = default_year
            return yr*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(yr)[2:]}"
    # Month + year only
    m = re.search(r'([A-Za-z]+)\s+(\d{4})', s)
    if m:
        mon, yr = m.group(1).lower()[:3], int(m.group(2))
        mo = MONTH_MAP.get(mon, 0)
        if mo and yr >= 2024:
            return yr*10000+mo*100+1, f"{MON_ABBR[mo]} {str(yr)[2:]}"
    return None, None

def get_wiki_html(page):
    data = json.loads(fetch("https://en.wikipedia.org/w/api.php", {
        "action":"parse","page":page,"prop":"text",
        "format":"json","disablelimitreport":"1",
    }))
    return data.get("parse",{}).get("text",{}).get("*","")

def get_row_cells(row_html):
    """Extract all td/th cell contents from a row, handling colspan by repeating."""
    cells = []
    for m in re.finditer(r'<t[dh]([^>]*)>(.*?)</t[dh]>', row_html, re.DOTALL):
        attrs, content = m.group(1), m.group(2)
        text = strip_tags(content)
        # Handle colspan
        cs = re.search(r'colspan=["\']?(\d+)["\']?', attrs)
        repeat = int(cs.group(1)) if cs else 1
        for _ in range(repeat):
            cells.append(text)
    return cells

def parse_vi_polls(html):
    """
    Parse all <tr> rows from the page, looking for rows that match
    the VI poll pattern: date | pollster | client | area | sample | Lab% | Con% | Ref% | LD% | Grn%
    """
    all_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    print(f"  Total <tr> rows in page: {len(all_rows)}", file=sys.stderr)

    # Find column map from header rows
    col = {}
    for row_html in all_rows:
        cells = get_row_cells(row_html)
        texts_lower = [c.lower().strip() for c in cells]
        found = {}
        for i, t in enumerate(texts_lower):
            if t in ('ref', 'reform uk', 'reform'): found['ref'] = i
            if t in ('lab', 'labour'): found['lab'] = i
            if t in ('con', 'conservative'): found['con'] = i
            if t in ('ld', 'lib dem', 'lib dems', 'liberal democrat'): found['lib'] = i
            if t in ('grn', 'green'): found['grn'] = i
            if 'sample' in t or t == 'n': found['n'] = i
            if 'conducted' in t or 'fieldwork' in t or t == 'date': found['date'] = i
            if t in ('pollster', 'firm', 'polling firm'): found['pollster'] = i
        if all(k in found for k in ['ref','lab','con','lib','grn']):
            col = found
            print(f"  Column map found: {col}", file=sys.stderr)
            print(f"  Header row: {cells}", file=sys.stderr)
            break

    if not col:
        print("  ERROR: could not find column headers", file=sys.stderr)
        # Try to infer from a known data row pattern
        return []

    polls = []
    current_year = None

    for row_html in all_rows:
        cells = get_row_cells(row_html)
        if len(cells) < 6:
            continue

        # Detect year rows (Wikipedia uses year as section header in tables)
        joined = ' '.join(cells).strip()
        yr_m = re.match(r'^(202[4-9])\s*$', joined)
        if yr_m:
            current_year = int(yr_m.group(1))
            continue

        # Skip if no % signs (header/spacer rows)
        if '%' not in joined:
            continue

        # Get party values using column map
        def gcol(k, default=None):
            idx = col.get(k, default)
            if idx is not None and idx < len(cells):
                return clean_pct(cells[idx])
            return None

        ref = gcol('ref')
        lab = gcol('lab')
        con = gcol('con')
        lib = gcol('lib')
        grn = gcol('grn')

        if not all([ref, lab, con, lib, grn]):
            continue

        # Sanity check on values
        if not (5<=ref<=50 and 5<=lab<=55 and 5<=con<=50 and 3<=lib<=30 and 3<=grn<=30):
            continue

        # Get date
        d_idx = col.get('date', 0)
        date_text = cells[d_idx] if d_idx < len(cells) else ''
        sort_key, date_str = parse_date(date_text, current_year)
        if not sort_key:
            for c in cells:
                sort_key, date_str = parse_date(c, current_year)
                if sort_key: break
        if not sort_key:
            continue

        # Get sample
        n = None
        n_idx = col.get('n')
        if n_idx is not None and n_idx < len(cells):
            raw = re.sub(r'[^0-9]','',cells[n_idx])
            if raw and 500 <= int(raw) <= 5000:
                n = int(raw)
        if not n:
            for c in cells:
                raw = re.sub(r'[^0-9]','',c)
                if raw and 500 <= int(raw) <= 5000:
                    n = int(raw); break
        if not n:
            continue

        # Get pollster
        pollster = None
        p_idx = col.get('pollster', 1)
        for ci in range(min(4, len(cells))):
            clean = re.sub(r'\s*\[?\d+\]?\s*$', '', cells[ci]).strip()
            for known in KNOWN_POLLSTERS:
                if known.lower() in clean.lower():
                    pollster = known; break
            if pollster: break
        if not pollster:
            raw = cells[p_idx] if p_idx < len(cells) else cells[1]
            raw = re.sub(r'\s*\[?\d+\]?\s*$', '', raw).strip()
            if 2 < len(raw) < 35 and raw[0].isupper():
                pollster = raw
            else:
                continue

        polls.append({
            'pollster': pollster,
            'client': cells[col.get('pollster',1)+1][:40] if col.get('pollster',1)+1 < len(cells) else '',
            'date': date_str,
            'sort_key': sort_key,
            'n': n,
            'ref':ref,'lab':lab,'con':con,'lib':lib,'grn':grn,
            'src': POLLSTER_SRCS.get(pollster,''),
        })

    print(f"  Raw polls found: {len(polls)}", file=sys.stderr)
    if polls:
        for p in polls[:3]:
            print(f"  {p['pollster']} {p['date']}: Ref{p['ref']} Lab{p['lab']} Con{p['con']} LD{p['lib']} Grn{p['grn']} n={p['n']}", file=sys.stderr)

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
    all_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    results = {}
    current_leader = None

    for heading in re.findall(r'<h[2-4][^>]*>(.*?)</h[2-4]>', html, re.DOTALL):
        ht = strip_tags(heading)
        for name in LEADER_MAP:
            if name.split()[-1] in ht and name.split()[0] in ht:
                current_leader = name

    for row_html in all_rows:
        cells = get_row_cells(row_html)
        full = ' '.join(cells)

        for name in LEADER_MAP:
            if name.split()[-1] in full and len(full) < 100:
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

        nums = [v for c in cells if (v:=clean_pct(c)) is not None and 10<=v<=80]
        if len(nums) < 2: continue
        approve, disapprove = nums[0], nums[1]
        if approve+disapprove > 130: continue

        if current_leader not in results or sort_key > results[current_leader]['sort_key']:
            results[current_leader] = {'sort_key':sort_key,'date':date_str,
                'pollster':pollster,'approve':approve,'disapprove':disapprove}

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

    print("Fetching VI polls...", file=sys.stderr)
    vi_html = get_wiki_html(VI_PAGE)
    print(f"  HTML: {len(vi_html)} chars", file=sys.stderr)

    polls = parse_vi_polls(vi_html)
    print(f"  Total unique polls: {len(polls)}", file=sys.stderr)

    if not polls:
        print("ERROR: no polls parsed", file=sys.stderr)
        sys.exit(1)

    monthly = build_monthly_history(polls)
    print(f"  Monthly: {monthly['labels']}", file=sys.stderr)

    print("Fetching leaders...", file=sys.stderr)
    try:
        la_html = get_wiki_html(LA_PAGE)
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

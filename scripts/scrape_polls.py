#!/usr/bin/env python3
"""
Scrapes UK VI polls from Wikipedia using the HTML API (cleaner than wikitext).
Writes polls.json to stdout.
"""
import json, re, sys
from datetime import datetime
from collections import defaultdict

try:
    import requests
    def fetch(url, params=None):
        r = requests.get(url, params=params,
            headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"},
            timeout=30)
        r.raise_for_status()
        return r.text
except ImportError:
    import urllib.request, urllib.parse
    def fetch(url, params=None):
        if params:
            url += '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url,
            headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode()

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
    'Andy Burnham':  {'party':'lab','role':'Labour leader'},
    'Keir Starmer':  {'party':'lab','role':'Former PM'},
    'Kemi Badenoch': {'party':'con','role':'Conservative leader'},
    'Nigel Farage':  {'party':'ref','role':'Reform UK leader'},
    'Ed Davey':      {'party':'lib','role':'Lib Dem leader'},
    'Zack Polanski': {'party':'grn','role':'Green leader'},
    'Angela Rayner': {'party':'lab','role':'Deputy Labour leader'},
}

def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip()

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

def fetch_html_table(page_title):
    """Fetch page HTML via Wikipedia REST API and extract table rows as lists of strings."""
    html = fetch(f"https://en.wikipedia.org/api/rest_v1/page/html/{urllib.parse.quote(page_title) if 'urllib' in dir() else page_title.replace(' ','_')}")
    # Extract all <tr> rows
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    result = []
    for row in rows:
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
        result.append([strip_tags(c) for c in cells])
    return result

def parse_vi_polls(page_title):
    """
    Parse VI polling table from Wikipedia HTML.
    Columns (typical): Pollster | Client | Dates | Sample | Ref | Lab | Con | LD | Grn | Oth | Lead
    """
    try:
        rows = fetch_html_table(page_title)
    except Exception as e:
        print(f"  HTML fetch failed: {e}, trying wikitext...", file=sys.stderr)
        return parse_vi_from_wikitext(page_title)

    polls = []
    for cells in rows:
        if len(cells) < 7:
            continue

        # Skip header rows
        if any(h in cells[0].lower() for h in ['pollster','firm','company','poll']):
            continue

        # Find pollster
        pollster = None
        for ci in range(min(3, len(cells))):
            for known in KNOWN_POLLSTERS:
                if known.lower() in cells[ci].lower():
                    pollster = known; break
            if pollster: break
        if not pollster:
            if 2 < len(cells[0]) < 35:
                pollster = cells[0]
            else:
                continue

        # Find date
        sort_key, date_str = None, None
        for c in cells[1:6]:
            sk, ds = parse_date(c)
            if sk and sk > 20240700:
                sort_key, date_str = sk, ds; break
        if not sort_key:
            continue

        # Sample size: 500-5000 for standard polls (filter out MRP which are >5000)
        n = None
        for c in cells:
            raw = re.sub(r'[^0-9]', '', c)
            if raw and 500 <= int(raw) <= 5000:
                n = int(raw); break

        # Skip if no sample found (likely MRP or sub-group poll)
        if not n:
            continue

        # Extract percentages: 5 values summing to 85-105%
        nums = []
        for c in cells:
            v = clean_num(c)
            if v is not None and 3 <= v <= 55:
                nums.append(v)

        best = None
        for i in range(len(nums)):
            for w in [5, 6]:
                sub = nums[i:i+w]
                if len(sub) >= 5 and 85 <= sum(sub[:5]) <= 105:
                    best = sub[:5]; break
            if best: break

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

    print(f"  Parsed {len(unique)} VI polls from HTML", file=sys.stderr)
    return unique[:50]

def parse_vi_from_wikitext(page_title):
    """Fallback: fetch raw wikitext and parse more carefully."""
    try:
        import urllib.parse as up
    except: pass
    wikitext = fetch("https://en.wikipedia.org/w/api.php", {
        "action":"parse","page":page_title,"prop":"wikitext","format":"json"
    })
    data = json.loads(wikitext)
    wt = data.get("parse",{}).get("wikitext",{}).get("*","")

    polls = []
    # Find all table rows with | at start
    for row in re.split(r'\n\|-+', wt):
        row = row.replace('||','\n|')
        cells_raw = re.findall(r'^\|([^|\n!][^\n]*)', row, re.MULTILINE)
        cells = []
        for c in cells_raw:
            c = re.sub(r'\{\{[^}]*\}\}','',c)
            c = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]',r'\1',c)
            c = re.sub(r'<[^>]+>','',c)
            c = c.strip()
            if c: cells.append(c)

        if len(cells) < 7: continue

        pollster = None
        for ci in range(min(2,len(cells))):
            for known in KNOWN_POLLSTERS:
                if known.lower() in cells[ci].lower():
                    pollster = known; break
            if pollster: break
        if not pollster: continue

        sort_key, date_str = None, None
        for c in cells[1:5]:
            sk, ds = parse_date(c)
            if sk and sk > 20240700:
                sort_key, date_str = sk, ds; break
        if not sort_key: continue

        # Only standard polls (n=500-5000)
        n = None
        for c in cells:
            raw = re.sub(r'[^0-9]','',c)
            if raw and 500 <= int(raw) <= 5000:
                n = int(raw); break
        if not n: continue

        nums = [v for c in cells if (v:=clean_num(c)) is not None and 3<=v<=55]
        best = None
        for i in range(len(nums)):
            sub = nums[i:i+5]
            if len(sub)==5 and 85<=sum(sub)<=105:
                best=sub; break
        if not best: continue

        ref,lab,con,lib,grn = best
        polls.append({'pollster':pollster,'client':cells[1][:40],'date':date_str,
                      'sort_key':sort_key,'n':n,'ref':ref,'lab':lab,'con':con,
                      'lib':lib,'grn':grn,'src':POLLSTER_SRCS.get(pollster,'')})

    seen,unique=[],[]
    seen_set=set()
    for p in sorted(polls,key=lambda x:-x['sort_key']):
        k=(p['pollster'],p['sort_key'])
        if k not in seen_set:
            seen_set.add(k); unique.append(p)
    print(f"  Parsed {len(unique)} polls from wikitext fallback", file=sys.stderr)
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

def parse_leader_approval(page_title):
    try:
        rows = fetch_html_table(page_title)
    except Exception as e:
        print(f"  Leader HTML fetch failed: {e}", file=sys.stderr)
        return []

    results = {}
    current_leader = None

    for cells in rows:
        if not cells: continue
        full = ' '.join(cells)

        # Detect leader section heading
        for name in LEADER_MAP:
            last = name.split()[-1]
            if last in full and len(full) < 60:
                current_leader = name; break

        if not current_leader or len(cells) < 4:
            continue

        # Find pollster
        pollster = ''
        for c in cells:
            for known in KNOWN_POLLSTERS:
                if known.lower() in c.lower():
                    pollster = known; break
            if pollster: break

        # Find date
        sort_key, date_str = None, None
        for c in cells:
            sk, ds = parse_date(c)
            if sk and sk > 20240700:
                sort_key, date_str = sk, ds; break
        if not sort_key: continue

        # Find approve/disapprove (two % values 10-80)
        nums = [v for c in cells if (v:=clean_num(c)) is not None and 10<=v<=80]
        if len(nums) < 2: continue

        approve, disapprove = nums[0], nums[1]
        if approve + disapprove > 130: continue  # sanity check

        if current_leader not in results or sort_key > results[current_leader]['sort_key']:
            results[current_leader] = {
                'sort_key': sort_key, 'date': date_str,
                'pollster': pollster, 'approve': approve, 'disapprove': disapprove,
            }

    output = []
    for name, r in results.items():
        src = f"YouGov · {r['date']}" if r['pollster']=='YouGov' else f"{r['pollster']} · {r['date']}"
        output.append({'name':name,'approve':r['approve'],'disapprove':r['disapprove'],
                       'net':r['approve']-r['disapprove'],'src':src})
        print(f"  {name}: {r['approve']}%/{r['disapprove']}% ({src})", file=sys.stderr)

    return output

def main():
    import urllib.parse

    VI_PAGE = "Opinion_polling_for_the_next_United_Kingdom_general_election"
    LA_PAGE = "Leadership_approval_opinion_polling_for_the_next_United_Kingdom_general_election"

    print("Fetching VI polls (HTML)...", file=sys.stderr)
    polls = parse_vi_polls(VI_PAGE)

    if not polls:
        print("ERROR: no polls parsed", file=sys.stderr); sys.exit(1)

    # Print sample for debugging
    for p in polls[:3]:
        print(f"  {p['pollster']} {p['date']}: Ref{p['ref']} Lab{p['lab']} Con{p['con']} LD{p['lib']} Grn{p['grn']} n={p['n']}", file=sys.stderr)

    monthly = build_monthly_history(polls)
    print(f"  {len(monthly['labels'])} monthly averages: {monthly['labels']}", file=sys.stderr)

    print("Fetching leader approval...", file=sys.stderr)
    try:
        leaders = parse_leader_approval(LA_PAGE)
    except Exception as e:
        print(f"  WARNING: {e}", file=sys.stderr); leaders = []

    for p in polls: p.pop('sort_key', None)

    now = datetime.now(__import__('timezone',fromlist=['UTC']).UTC) if hasattr(datetime,'now') else datetime.utcnow()
    print(json.dumps({
        'generated': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'monthly_history': monthly,
        'recent_polls': polls[:10],
        'leader_approval': leaders,
    }, indent=2))

    print(f"\nDone: {len(polls)} polls · {len(monthly['labels'])} months · {len(leaders)} leaders", file=sys.stderr)

if __name__ == '__main__':
    main()

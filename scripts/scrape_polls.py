#!/usr/bin/env python3
"""
Scrapes UK VI polls from Wikipedia.
Auto-detects column positions from header row.
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
    'Freshwater':'freshwaterstrategy.com','Focaldata':'focaldata.com',
    'Verian':'verian.com',
}
KNOWN_POLLSTERS = list(POLLSTER_SRCS.keys())

LEADER_MAP = {
    'Andy Burnham':'lab','Keir Starmer':'lab','Kemi Badenoch':'con',
    'Nigel Farage':'ref','Ed Davey':'lib','Zack Polanski':'grn','Angela Rayner':'lab',
}

LEADER_FALLBACK = {
    'Andy Burnham':   {'approve':45,'disapprove':40,'net':5,  'src':'YouGov · Jun 2026'},
    'Zack Polanski':  {'approve':29,'disapprove':38,'net':-9, 'src':'YouGov · Jun 2026'},
    'Ed Davey':       {'approve':32,'disapprove':44,'net':-12,'src':'YouGov · Jun 2026'},
    'Kemi Badenoch':  {'approve':25,'disapprove':51,'net':-26,'src':'YouGov · Jun 2026'},
    'Nigel Farage':   {'approve':28,'disapprove':58,'net':-30,'src':'YouGov · Jun 2026'},
    'Angela Rayner':  {'approve':21,'disapprove':51,'net':-30,'src':'Opinium · Jun 2026'},
    'Keir Starmer':   {'approve':19,'disapprove':62,'net':-43,'src':'YouGov · Jun 2026'},
}

def fetch_wiki(page):
    url = "https://en.wikipedia.org/w/api.php"
    params = urllib.parse.urlencode({
        "action":"parse","page":page,"prop":"text",
        "format":"json","disablelimitreport":"1"
    })
    req = urllib.request.Request(f"{url}?{params}",
        headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8')).get("parse",{}).get("text",{}).get("*","")

try:
    import requests
    def fetch_wiki(page):
        r = requests.get("https://en.wikipedia.org/w/api.php",
            params={"action":"parse","page":page,"prop":"text","format":"json","disablelimitreport":"1"},
            headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"},
            timeout=30)
        r.raise_for_status()
        return r.json().get("parse",{}).get("text",{}).get("*","")
except ImportError:
    pass

def st(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'&[a-zA-Z0-9]+;', ' ', s)
    s = re.sub(r'&#\d+;', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def pct(s):
    s = st(s).replace('%','').strip()
    m = re.search(r'^(\d+(?:\.\d+)?)$', s)
    try: return round(float(m.group(1))) if m else None
    except: return None

def parse_date(s):
    """Parse a date string that contains a full year. Returns (sortkey, display) or (None, None)."""
    s = st(s).replace('–','-').replace('—','-')
    # "9-10 May 2026" or "9 May 2026"
    m = re.search(r'(\d{1,2})(?:\s*-\s*\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})', s)
    if m:
        d, mo, y = int(m.group(1)), MONTH_MAP.get(m.group(2).lower()[:3], 0), int(m.group(3))
        if mo and 2024 <= y <= 2030:
            return y*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(y)[2:]}"
    # "May 2026"
    m = re.search(r'([A-Za-z]+)\s+(\d{4})', s)
    if m:
        mo, y = MONTH_MAP.get(m.group(1).lower()[:3], 0), int(m.group(2))
        if mo and 2024 <= y <= 2030:
            return y*10000+mo*100+1, f"{MON_ABBR[mo]} {str(y)[2:]}"
    return None, None

def row_cells(row_html):
    return [st(m.group(1)) for m in re.finditer(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL)]

def detect_columns(rows):
    """Scan rows to find a header row and map column names to indices."""
    for cells in rows[:20]:
        t = [c.lower().strip() for c in cells]
        col = {}
        for i, c in enumerate(t):
            if c in ('ref','reform'): col['ref'] = i
            elif c in ('lab','labour'): col['lab'] = i
            elif c in ('con','conservative'): col['con'] = i
            elif c in ('ld','lib dem','lib dems'): col['lib'] = i
            elif c in ('grn','green'): col['grn'] = i
            elif 'sample' in c or c == 'n': col['n'] = i
            elif 'date' in c or 'fieldwork' in c or 'conducted' in c: col['date'] = i
            elif c in ('pollster','polling firm','firm'): col['pollster'] = i
        if all(k in col for k in ['ref','lab','con','lib','grn']):
            print(f"  Auto-detected cols: {col}", file=sys.stderr)
            return col
    return None

def parse_vi(html):
    all_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    parsed_rows = [row_cells(r) for r in all_rows]
    print(f"  Total rows: {len(parsed_rows)}", file=sys.stderr)

    col = detect_columns(parsed_rows)
    if not col:
        # Fallback to known positions
        col = {'date':0,'pollster':1,'n':4,'lab':5,'con':6,'ref':7,'lib':8,'grn':9}
        print(f"  Using fallback cols: {col}", file=sys.stderr)

    today = datetime.utcnow()
    polls = []

    for cells in parsed_rows:
        if len(cells) < 6: continue
        raw = ' '.join(cells)
        if '%' not in raw: continue

        # Get party values
        def gc(k):
            idx = col.get(k)
            return pct(cells[idx]) if idx is not None and idx < len(cells) else None

        ref,lab,con,lib,grn = gc('ref'),gc('lab'),gc('con'),gc('lib'),gc('grn')
        if not all(v is not None for v in [ref,lab,con,lib,grn]): continue
        if not (5<=ref<=50 and 5<=lab<=55 and 5<=con<=50 and 3<=lib<=30 and 3<=grn<=30): continue

        # Find date — scan all cells for a full date with year
        sk, ds = None, None
        d_idx = col.get('date', 0)
        if d_idx < len(cells):
            sk, ds = parse_date(cells[d_idx])
        if not sk:
            for c in cells:
                sk, ds = parse_date(c)
                if sk: break
        if not sk: continue

        # Reject future dates and pre-election dates
        yr = sk // 10000
        mo = (sk % 10000) // 100
        if yr > today.year or (yr == today.year and mo > today.month + 1): continue
        if sk < 20240705: continue

        # Sample size
        n = None
        n_idx = col.get('n')
        if n_idx is not None and n_idx < len(cells):
            raw_n = re.sub(r'[^0-9]','',cells[n_idx])
            if raw_n and 500 <= int(raw_n) <= 6000: n = int(raw_n)
        if not n:
            for c in cells:
                raw_n = re.sub(r'[^0-9]','',c)
                if raw_n and 500 <= int(raw_n) <= 6000: n = int(raw_n); break
        if not n: continue

        # Pollster
        pollster = None
        for ci in range(min(4, len(cells))):
            clean = re.sub(r'\s*\[?\d+\]?$','',cells[ci]).strip()
            for known in KNOWN_POLLSTERS:
                if known.lower() in clean.lower(): pollster = known; break
            if pollster: break
        if not pollster:
            p_idx = col.get('pollster', 1)
            raw_p = re.sub(r'\s*\[?\d+\]?$','',cells[p_idx] if p_idx < len(cells) else '').strip()
            if 2 < len(raw_p) < 35 and raw_p[0].isupper(): pollster = raw_p
            else: continue

        polls.append({'pollster':pollster,'date':ds,'sort_key':sk,'n':n,
                      'ref':ref,'lab':lab,'con':con,'lib':lib,'grn':grn,
                      'client':'','src':POLLSTER_SRCS.get(pollster,'')})

    print(f"  Raw polls: {len(polls)}", file=sys.stderr)
    seen, unique = set(), []
    for p in sorted(polls, key=lambda x: -x['sort_key']):
        k = (p['pollster'], p['sort_key'])
        if k not in seen: seen.add(k); unique.append(p)
    print(f"  Unique: {len(unique)}", file=sys.stderr)
    if unique:
        print(f"  Latest: {unique[0]['pollster']} {unique[0]['date']} Ref{unique[0]['ref']} Lab{unique[0]['lab']}", file=sys.stderr)
    return unique[:50]

def build_monthly(polls):
    bm = defaultdict(list)
    for p in polls: bm[p['sort_key']//100].append(p)
    labels,ra,la,ca,ga,lia=[],[],[],[],[],[]
    avg = lambda lst,k: round(sum(x[k] for x in lst)/len(lst),1)
    for ym in sorted(bm):
        mo=ym%100; g=bm[ym]
        labels.append(f"{MON_ABBR[mo]} {str(ym//100)[2:]}")
        ra.append(avg(g,'ref')); la.append(avg(g,'lab')); ca.append(avg(g,'con'))
        ga.append(avg(g,'grn')); lia.append(avg(g,'lib'))
    return {'labels':labels,'ref':ra,'lab':la,'con':ca,'grn':ga,'lib':lia}

def parse_leaders(html):
    all_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    results = {}; cur = None
    for h in re.findall(r'<h[2-4][^>]*>(.*?)</h[2-4]>', html, re.DOTALL):
        ht = st(h)
        for name in LEADER_MAP:
            if name.split()[-1] in ht and name.split()[0] in ht: cur = name
    for r in all_rows:
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
        nums = [v for c in cells if (v:=pct(c)) is not None and 10<=v<=80]
        if len(nums) < 2: continue
        ap, di = nums[0], nums[1]
        if ap+di > 130: continue
        if cur not in results or sk > results[cur]['sk']:
            results[cur] = {'sk':sk,'date':ds,'pollster':pollster,'approve':ap,'disapprove':di}

    out = []
    for name in LEADER_MAP:
        if name in results:
            r = results[name]
            src = f"YouGov · {r['date']}" if r['pollster']=='YouGov' else f"{r['pollster']} · {r['date']}"
            entry = {'name':name,'approve':r['approve'],'disapprove':r['disapprove'],
                     'net':r['approve']-r['disapprove'],'src':src}
            print(f"  {name}: {r['approve']}%/{r['disapprove']}% ({src}) [Wikipedia]", file=sys.stderr)
        elif name in LEADER_FALLBACK:
            fb = LEADER_FALLBACK[name]
            entry = {'name':name,'approve':fb['approve'],'disapprove':fb['disapprove'],
                     'net':fb['net'],'src':fb['src']}
            print(f"  {name}: {fb['approve']}%/{fb['disapprove']}% ({fb['src']}) [fallback]", file=sys.stderr)
        else:
            continue
        out.append(entry)
    return out

def main():
    VI = "Opinion_polling_for_the_next_United_Kingdom_general_election"
    LA = "Leadership_approval_opinion_polling_for_the_next_United_Kingdom_general_election"

    print("Fetching VI...", file=sys.stderr)
    vi_html = fetch_wiki(VI)
    print(f"  HTML: {len(vi_html)} chars", file=sys.stderr)

    polls = parse_vi(vi_html)
    if not polls:
        print("ERROR: no polls", file=sys.stderr); sys.exit(1)

    monthly = build_monthly(polls)
    print(f"  Monthly labels: {monthly['labels']}", file=sys.stderr)

    print("Fetching leaders...", file=sys.stderr)
    try:
        la_html = fetch_wiki(LA)
        leaders = parse_leaders(la_html)
        print(f"  {len(leaders)} leaders", file=sys.stderr)
    except Exception as e:
        print(f"  WARNING: {e}", file=sys.stderr)
        leaders = [{'name':n,'approve':v['approve'],'disapprove':v['disapprove'],
                    'net':v['net'],'src':v['src']} for n,v in LEADER_FALLBACK.items()]

    for p in polls: p.pop('sort_key', None)

    print(json.dumps({
        'generated': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'monthly_history': monthly,
        'recent_polls': polls[:10],
        'leader_approval': leaders,
    }, indent=2))

    print(f"\nDone: {len(polls)} polls · {len(monthly['labels'])} months · {len(leaders)} leaders", file=sys.stderr)

if __name__ == '__main__': main()

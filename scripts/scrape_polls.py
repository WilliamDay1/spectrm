#!/usr/bin/env python3
"""
Scrapes UK VI polls from Wikipedia WIKITEXT (not rendered HTML).
The wikitext has explicit full dates on every row.
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
    'Verian':'verian.com','Good Growth':'goodgrowthfoundation.co.uk',
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

def fetch_wikitext(page):
    params = urllib.parse.urlencode({
        "action":"parse","page":page,"prop":"wikitext",
        "format":"json","disablelimitreport":"1"
    })
    req = urllib.request.Request(
        f"https://en.wikipedia.org/w/api.php?{params}",
        headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("parse",{}).get("wikitext",{}).get("*","")

try:
    import requests
    def fetch_wikitext(page):
        r = requests.get("https://en.wikipedia.org/w/api.php",
            params={"action":"parse","page":page,"prop":"wikitext","format":"json","disablelimitreport":"1"},
            headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"},
            timeout=30)
        r.raise_for_status()
        return r.json().get("parse",{}).get("wikitext",{}).get("*","")
except ImportError:
    pass

def clean(s):
    """Strip wikitext markup from a cell value."""
    s = re.sub(r'\{\{[^}]*\}\}', '', s)           # remove templates
    s = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', s)  # unwrap links
    s = re.sub(r'<ref[^>]*/>', '', s)              # remove ref tags
    s = re.sub(r'<ref[^>]*>.*?</ref>', '', s, flags=re.DOTALL)
    s = re.sub(r"'''?", '', s)                      # remove bold/italic
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def pct(s):
    """Extract integer percentage from a wikitext cell."""
    s = clean(s).replace('%','').strip()
    m = re.match(r'^(\d+(?:\.\d+)?)$', s)
    try: return round(float(m.group(1))) if m else None
    except: return None

def parse_date_with_year(s, yr):
    """Parse a date without an explicit year, using yr."""
    s = clean(s).replace('–','-').replace('—','-')
    m = re.search(r'(\d{1,2})(?:\s*-\s*\d{1,2})?\s+([A-Za-z]+)', s)
    if m and yr:
        d = int(m.group(1))
        mo = MONTH_MAP.get(m.group(2).lower()[:3], 0)
        if mo: return yr*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(yr)[2:]}"
    return None, None

def parse_date(s):
    """Parse date from wikitext cell — must contain a 4-digit year."""
    s = clean(s).replace('–','-').replace('—','-')
    # "21-22 Jun 2026" or "21 Jun 2026"
    m = re.search(r'(\d{1,2})(?:\s*-\s*\d{1,2})?\s+([A-Za-z]+)\s+(202[4-9])', s)
    if m:
        d = int(m.group(1))
        mo = MONTH_MAP.get(m.group(2).lower()[:3], 0)
        y = int(m.group(3))
        if mo: return y*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(y)[2:]}"
    # "Jun 2026"
    m = re.search(r'([A-Za-z]+)\s+(202[4-9])', s)
    if m:
        mo = MONTH_MAP.get(m.group(1).lower()[:3], 0)
        y = int(m.group(2))
        if mo: return y*10000+mo*100+1, f"{MON_ABBR[mo]} {str(y)[2:]}"
    return None, None

def parse_wikitext_rows(wikitext):
    """
    Parse wikitext table rows. Each row is delimited by |- 
    Cells within a row are delimited by || or newline + |
    """
    rows = []
    # Split on row separators
    for row_raw in re.split(r'\n\s*\|-+[^\n]*\n', wikitext):
        # Normalise: replace || with cell separator
        row_raw = row_raw.replace('||', '\n|')
        # Extract cells (lines starting with | but not ||, !, or |- )
        cells = []
        for line in row_raw.split('\n'):
            line = line.strip()
            if line.startswith('|') and not line.startswith('||') and not line.startswith('|}') and not line.startswith('|+'):
                cell = line[1:].strip()
                # Handle cells with style attributes: "style=...|actual content"
                if re.match(r'[a-z\-]+\s*=', cell):
                    parts = cell.split('|', 1)
                    cell = parts[-1].strip()
                cells.append(cell)
        if cells:
            rows.append(cells)
    return rows

def parse_vi(wikitext):
    today = datetime.utcnow()

    # Split wikitext into lines and process sequentially
    # tracking current year from == 2026 == style headings
    lines = wikitext.split('\n')
    cur_yr = None
    polls = []

    # First detect column map from header rows
    col = {'date':0,'pollster':1,'client':2,'area':3,'n':4,'lab':5,'con':6,'ref':7,'lib':8,'grn':9}

    # Parse rows by accumulating cells between |- row separators
    row_cells_acc = []
    in_row = False

    for line in lines:
        # Detect year headings: == 2026 == or === 2026 ===
        hm = re.match(r'^={2,4}\s*(202[4-9])\s*={2,4}', line)
        if hm:
            cur_yr = int(hm.group(1))
            print(f"  Year heading: {cur_yr}", file=sys.stderr)
            continue

        # Row separator
        if re.match(r'^\s*\|-', line):
            if row_cells_acc:
                _process_row(row_cells_acc, col, cur_yr, today, polls)
            row_cells_acc = []
            in_row = True
            continue

        # Cell line (starts with | but not |} or |- or |+)
        if line.startswith('|') and not line.startswith('|}') and not line.startswith('|-') and not line.startswith('|+') and not line.startswith('!'):
            # Handle || separated cells on one line
            parts = line[1:].split('||')
            for part in parts:
                part = part.strip()
                # Strip style attributes: "style=...|content"
                if re.match(r'[a-zA-Z\-]+\s*=', part):
                    sp = part.split('|', 1)
                    part = sp[-1].strip() if len(sp) > 1 else ''
                row_cells_acc.append(part)

    # Process last row
    if row_cells_acc:
        _process_row(row_cells_acc, col, cur_yr, today, polls)

    print(f"  Raw polls: {len(polls)}", file=sys.stderr)
    seen, unique = set(), []
    for p in sorted(polls, key=lambda x: -x['sort_key']):
        k = (p['pollster'], p['sort_key'])
        if k not in seen: seen.add(k); unique.append(p)

    if unique:
        print(f"  Latest: {unique[0]['pollster']} {unique[0]['date']}", file=sys.stderr)
        print(f"  Oldest: {unique[-1]['pollster']} {unique[-1]['date']}", file=sys.stderr)
    return unique[:50]

def _process_row(cells, col, cur_yr, today, polls):
    if len(cells) < 6: return
    raw = ' '.join(cells)
    if '%' not in raw: return

    def gc(k):
        idx = col.get(k)
        return pct(cells[idx]) if idx is not None and idx < len(cells) else None

    ref,lab,con,lib,grn = gc('ref'),gc('lab'),gc('con'),gc('lib'),gc('grn')
    if not all(v is not None for v in [ref,lab,con,lib,grn]): return
    if not (5<=ref<=50 and 5<=lab<=55 and 5<=con<=50 and 3<=lib<=30 and 3<=grn<=30): return

    # Date — try with 4-digit year first, then with cur_yr
    sk, ds = None, None
    d_idx = col.get('date', 0)
    dtxt = cells[d_idx] if d_idx < len(cells) else ''
    sk, ds = parse_date(dtxt)
    if not sk and cur_yr:
        sk, ds = parse_date_with_year(dtxt, cur_yr)
    if not sk: return

    yr, mo = sk//10000, (sk%10000)//100
    if sk < 20240705: return
    if yr > today.year or (yr == today.year and mo > today.month + 1): return

    # Sample size
    n = None
    n_idx = col.get('n')
    if n_idx is not None and n_idx < len(cells):
        raw_n = re.sub(r'[^0-9]','',clean(cells[n_idx]))
        if raw_n and 500 <= int(raw_n) <= 6000: n = int(raw_n)
    if not n:
        for c in cells:
            raw_n = re.sub(r'[^0-9]','',clean(c))
            if raw_n and 500 <= int(raw_n) <= 6000: n = int(raw_n); break
    if not n: return

    # Pollster
    pollster = None
    for ci in range(min(4, len(cells))):
        cv = re.sub(r'\s*\[?\d+\]?$','',clean(cells[ci])).strip()
        for known in KNOWN_POLLSTERS:
            if known.lower() in cv.lower(): pollster = known; break
        if pollster: break
    if not pollster:
        p_idx = col.get('pollster', 1)
        rp = re.sub(r'\s*\[?\d+\]?$','',clean(cells[p_idx]) if p_idx < len(cells) else '').strip()
        if 2 < len(rp) < 35 and rp[0].isupper(): pollster = rp
        else: return

    polls.append({'pollster':pollster,'date':ds,'sort_key':sk,'n':n,
                  'ref':ref,'lab':lab,'con':con,'lib':lib,'grn':grn,
                  'client':'','src':POLLSTER_SRCS.get(pollster,'')})

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

def parse_leaders(wikitext):
    rows = parse_wikitext_rows(wikitext)
    results = {}; cur = None

    # Find leader sections from headings
    for m in re.finditer(r'==+\s*([^=\n]+?)\s*==+', wikitext):
        heading = m.group(1).strip()
        for name in LEADER_MAP:
            if name.split()[-1] in heading and name.split()[0] in heading:
                cur = name; break

    for cells in rows:
        if not cells: continue
        full = ' '.join(clean(c) for c in cells)
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
            cv = clean(c)
            for known in KNOWN_POLLSTERS:
                if known.lower() in cv.lower(): pollster = known; break
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
            print(f"  {name}: {r['approve']}%/{r['disapprove']}% ({src})", file=sys.stderr)
        elif name in LEADER_FALLBACK:
            fb = LEADER_FALLBACK[name]
            entry = {'name':name,'approve':fb['approve'],'disapprove':fb['disapprove'],
                     'net':fb['net'],'src':fb['src']}
            print(f"  {name}: fallback", file=sys.stderr)
        else:
            continue
        out.append(entry)
    return out

def main():
    VI = "Opinion_polling_for_the_next_United_Kingdom_general_election"
    LA = "Leadership_approval_opinion_polling_for_the_next_United_Kingdom_general_election"

    print("Fetching VI wikitext...", file=sys.stderr)
    vi_wt = fetch_wikitext(VI)
    print(f"  Length: {len(vi_wt)} chars", file=sys.stderr)

    polls = parse_vi(vi_wt)
    if not polls:
        print("ERROR: no polls", file=sys.stderr); sys.exit(1)

    monthly = build_monthly(polls)
    print(f"  Monthly: {monthly['labels']}", file=sys.stderr)

    print("Fetching leader wikitext...", file=sys.stderr)
    try:
        la_wt = fetch_wikitext(LA)
        leaders = parse_leaders(la_wt)
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

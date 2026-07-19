#!/usr/bin/env python3
"""
Scrapes UK VI polls from Wikipedia parsed HTML.
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
    'Freshwater','Omnisis','Focaldata','Brains','Savanta',
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

def get_wiki_html(page):
    data = json.loads(fetch("https://en.wikipedia.org/w/api.php", {
        "action":"parse","page":page,"prop":"text",
        "format":"json","disablelimitreport":"1",
    }))
    return data.get("parse",{}).get("text",{}).get("*","")

def extract_tables(html):
    tables = []
    for table_html in re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL):
        rows = []
        for row_html in re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL):
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL)
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables

def parse_vi_polls(html):
    tables = extract_tables(html)
    print(f"  Found {len(tables)} tables total", file=sys.stderr)

    # Debug: print headers of first 10 tables to see structure
    for ti, table in enumerate(tables[:10]):
        for ri, row in enumerate(table[:3]):
            texts = [strip_tags(c)[:25] for c in row]
            print(f"  T{ti}R{ri}: {texts}", file=sys.stderr)

    all_polls = []

    for ti, table in enumerate(tables):
        # Look for the VI table: must have a row with Reform/Lab/Con/LD/Grn headers
        col = {}
        for row in table[:5]:
            texts = [strip_tags(c).lower() for c in row]
            for i, t in enumerate(texts):
                t_strip = t.strip()
                # Match exact Wikipedia header abbreviations
                if t_strip in ['ref','reform'] and 'ref' not in col:
                    col['ref'] = i
                if t_strip in ['lab','labour'] and 'lab' not in col:
                    col['lab'] = i
                if t_strip in ['con','conserv','conservative'] and 'con' not in col:
                    col['con'] = i
                if t_strip in ['ld','lib dem','liberal democrat','lib dems'] and 'lib' not in col:
                    col['lib'] = i
                if t_strip in ['grn','green'] and 'grn' not in col:
                    col['grn'] = i
                if any(x in t_strip for x in ['sample','size']) and 'n' not in col:
                    col['n'] = i
                if any(x in t_strip for x in ['date','fieldwork','conducted']) and 'date' not in col:
                    col['date'] = i
                if t_strip in ['pollster','firm','poll','company'] and 'pollster' not in col:
                    col['pollster'] = i

            if all(k in col for k in ['ref','lab','con']):
                break

        if not all(k in col for k in ['ref','lab','con']):
            continue

        print(f"  VI table found at T{ti}, cols={col}", file=sys.stderr)

        for row in table:
            texts = [strip_tags(c) for c in row]
            if len(texts) < 5:
                continue

            # Skip rows that are headers (no % values) or empty spacer rows
            raw_joined = ''.join([strip_tags(c) for c in row])
            if '%' not in raw_joined and not any(c.isdigit() for c in raw_joined):
                continue
            if len([c for c in row if strip_tags(c).strip()]) < 4:
                continue

            # Pollster — strip trailing footnote numbers e.g. "Find Out Now 164" -> "Find Out Now"
            pollster = None
            for ci in range(min(4, len(texts))):
                # Strip footnote reference numbers from end of pollster name
                clean = re.sub(r'\s*\d+$', '', texts[ci]).strip()
                for known in KNOWN_POLLSTERS:
                    if known.lower() in clean.lower():
                        pollster = known; break
                if pollster: break
            if not pollster:
                p_idx = col.get('pollster', 1)
                raw = texts[p_idx] if p_idx < len(texts) else texts[0]
                raw = re.sub(r'\s*\d+$', '', raw).strip()
                if 2 < len(raw) < 35 and raw[0].isupper():
                    pollster = raw
                else:
                    continue

            # Date — Wikipedia often omits year; infer from context
            sort_key, date_str = None, None
            d_idx = col.get('date', 0)
            date_text = texts[d_idx] if d_idx < len(texts) else ''
            # Try with year first
            sk, ds = parse_date(date_text)
            if sk and sk > 20240704:
                sort_key, date_str = sk, ds
            # If no year in date cell, try scanning all cells
            if not sort_key:
                for c in texts:
                    sk, ds = parse_date(c)
                    if sk and sk > 20240704:
                        sort_key, date_str = sk, ds; break
            # If still no year, try appending recent years to the date
            if not sort_key and date_text:
                for yr in ['2026', '2025', '2024']:
                    sk, ds = parse_date(date_text + ' ' + yr)
                    if sk and sk > 20240704:
                        sort_key, date_str = sk, ds; break
            if not sort_key:
                continue

            # Sample 500-5000 (strip commas from numbers like 2,930)
            n = None
            n_idx = col.get('n')
            if n_idx is not None and n_idx < len(texts):
                raw = re.sub(r'[^0-9]','',texts[n_idx])
                if raw and 500 <= int(raw) <= 5000:
                    n = int(raw)
            if not n:
                for c in texts:
                    raw = re.sub(r'[^0-9]','',c)
                    if raw and 500 <= int(raw) <= 5000:
                        n = int(raw); break
            if not n:
                continue

            # Party values
            def get_col(k):
                idx = col.get(k)
                if idx is not None and idx < len(texts):
                    return clean_pct(texts[idx])
                return None

            ref = get_col('ref')
            lab = get_col('lab')
            con = get_col('con')
            lib = get_col('lib')
            grn = get_col('grn')

            # Fallback: scan all cells for 5 consecutive plausible % values
            if not all([ref, lab, con, lib, grn]):
                nums = [v for c in texts if (v:=clean_pct(c)) is not None and 3 <= v <= 55]
                for i in range(len(nums)):
                    sub = nums[i:i+5]
                    if len(sub)==5 and 60 <= sum(sub) <= 115:
                        ref,lab,con,lib,grn = sub; break

            if not all([ref, lab, con, lib, grn]):
                continue

            # Sanity check
            if not (8<=ref<=45 and 10<=lab<=50 and 5<=con<=45 and 3<=lib<=30 and 3<=grn<=30):
                continue

            all_polls.append({
                'pollster': pollster,
                'client': texts[1][:40] if len(texts)>1 else '',
                'date': date_str,
                'sort_key': sort_key,
                'n': n,
                'ref':ref,'lab':lab,'con':con,'lib':lib,'grn':grn,
                'src': POLLSTER_SRCS.get(pollster,''),
            })

    seen, unique = set(), []
    for p in sorted(all_polls, key=lambda x: -x['sort_key']):
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
    tables = extract_tables(html)
    results = {}
    current_leader = None

    for heading in re.findall(r'<h[2-4][^>]*>(.*?)</h[2-4]>', html, re.DOTALL):
        ht = strip_tags(heading)
        for name in LEADER_MAP:
            if name.split()[-1] in ht:
                current_leader = name

    for table in tables:
        for row in table:
            texts = [strip_tags(c) for c in row]
            full = ' '.join(texts)
            for name in LEADER_MAP:
                if name.split()[-1] in full and len(full) < 80:
                    current_leader = name; break
            if not current_leader or len(texts) < 3:
                continue
            sort_key, date_str = None, None
            for c in texts:
                sk, ds = parse_date(c)
                if sk and sk > 20240700:
                    sort_key, date_str = sk, ds; break
            if not sort_key:
                continue
            pollster = ''
            for c in texts:
                for known in KNOWN_POLLSTERS:
                    if known.lower() in c.lower():
                        pollster = known; break
                if pollster: break
            nums = [v for c in texts if (v:=clean_pct(c)) is not None and 10<=v<=80]
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
    print(f"  Total: {len(polls)} polls", file=sys.stderr)

    if not polls:
        print("ERROR: no polls parsed", file=sys.stderr)
        sys.exit(1)

    for p in polls[:5]:
        print(f"  {p['pollster']} {p['date']}: Ref{p['ref']} Lab{p['lab']} Con{p['con']} LD{p['lib']} Grn{p['grn']} n={p['n']}", file=sys.stderr)

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

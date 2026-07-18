#!/usr/bin/env python3
"""
Scrapes UK opinion polling + leader approval from Wikipedia.
Writes polls.json to stdout.
"""

import json, re, sys
from datetime import datetime
from collections import defaultdict

try:
    import requests
    def fetch_wikitext(page_title):
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action":"parse","page":page_title,"prop":"wikitext","format":"json"},
            headers={"User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"},
            timeout=30
        )
        r.raise_for_status()
        return r.json().get("parse",{}).get("wikitext",{}).get("*","")
except ImportError:
    import urllib.request, urllib.parse
    def fetch_wikitext(page_title):
        url = (
            "https://en.wikipedia.org/w/api.php"
            "?action=parse&page=" + urllib.parse.quote(page_title) +
            "&prop=wikitext&format=json"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent":"Spectrm/1.0 (https://spectrm.uk; polls@spectrm.uk)"
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()).get("parse",{}).get("wikitext",{}).get("*","")

VI_PAGE = "Opinion_polling_for_the_next_United_Kingdom_general_election"
LA_PAGE = "Leadership_approval_opinion_polling_for_the_next_United_Kingdom_general_election"

MONTH_MAP = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12
}
MON_ABBR = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

POLLSTER_SRCS = {
    'YouGov':'yougov.com',
    'More in Common':'moreincommon.org.uk',
    'Opinium':'opinium.com',
    'Survation':'survation.com',
    'Savanta':'savanta.com',
    'Ipsos':'ipsos.com',
    'JL Partners':'jlpartners.co.uk',
    'Find Out Now':'findoutnow.co.uk',
    'Ashcroft':'lordashcroftpolls.com',
    'Redfield':'redfieldandwiltonstrategies.com',
    'BMG':'bmgresearch.co.uk',
    'Deltapoll':'deltapoll.co.uk',
    'Techne':'techneuk.co.uk',
    'Norstat':'norstat.co.uk',
    'Panelbase':'panelbase.net',
    'Number Cruncher':'numbercruncher.co.uk',
    'Omnisis':'omnisis.co.uk',
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

def strip_wiki(s):
    # Remove templates like {{foo}}
    s = re.sub(r'\{\{[^{}]*\}\}', '', s)
    # Unwrap wikilinks [[target|label]] -> label
    s = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', s)
    # Remove ref tags
    s = re.sub(r'<ref[^>]*/>', '', s)
    s = re.sub(r'<ref[^>]*>.*?</ref>', '', s, flags=re.DOTALL)
    return s.strip()

def clean_num(s):
    s = re.sub(r'[^0-9.]', '', strip_wiki(s))
    try:
        return round(float(s))
    except:
        return None

def parse_date(s):
    s = strip_wiki(s).replace('–','-').replace('—','-').replace('&ndash;','-')
    # "21-22 Jun 2026" or "21 Jun 2026"
    m = re.search(r'(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s+([A-Za-z]+)\s+(\d{4})', s)
    if m:
        d, mon, yr = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        mo = MONTH_MAP.get(mon, 0)
        if mo and yr >= 2024:
            return yr*10000+mo*100+d, f"{d} {MON_ABBR[mo]} {str(yr)[2:]}"
    # "Jun 2026"
    m = re.search(r'([A-Za-z]+)\s+(\d{4})', s)
    if m:
        mon, yr = m.group(1).lower()[:3], int(m.group(2))
        mo = MONTH_MAP.get(mon, 0)
        if mo and yr >= 2024:
            return yr*10000+mo*100+1, f"{MON_ABBR[mo]} {str(yr)[2:]}"
    return None, None

def parse_vi_polls(wikitext):
    """
    Wikipedia VI tables use this row format:
    |-
    | [[Pollster]] || [[Client]] || dates || sample || ref% || lab% || con% || ld% || grn% || ...
    
    We split on |- and parse each row.
    """
    polls = []

    # Normalise: replace || with \n| so every cell starts on new line with |
    wikitext = wikitext.replace('||', '\n|')

    for row in re.split(r'\n\s*\|-+[^\n]*\n', wikitext):
        # Get all cells: lines starting with |
        raw_cells = re.findall(r'^\|([^\n|!][^\n]*)', row, re.MULTILINE)
        cells = [strip_wiki(c).strip() for c in raw_cells]
        cells = [c for c in cells if c]  # remove empty

        if len(cells) < 6:
            continue

        # Find pollster in first 2 cells
        pollster = None
        for ci in range(min(2, len(cells))):
            for known in POLLSTER_SRCS:
                if known.lower() in cells[ci].lower():
                    pollster = known
                    break
            if pollster:
                break
        if not pollster:
            raw = cells[0]
            if 2 < len(raw) < 40 and not raw.startswith('!'):
                pollster = raw
            else:
                continue

        # Find date (post Jul 2024)
        sort_key, date_str = None, None
        for c in cells[:6]:
            sk, ds = parse_date(c)
            if sk and sk > 20240700:
                sort_key, date_str = sk, ds
                break
        if not sort_key:
            continue

        # Sample size: integer 500-20000
        n = None
        for c in cells:
            raw = re.sub(r'[^0-9]', '', c)
            if raw and 500 <= int(raw) <= 20000:
                n = int(raw)
                break

        # Extract all plausible % values (3-60)
        nums = []
        for c in cells:
            v = clean_num(c)
            if v is not None and 3 <= v <= 60:
                nums.append(v)

        # Find 5 consecutive values summing 68-115
        best = None
        for i in range(len(nums)):
            for length in [5, 6]:
                if i + length > len(nums):
                    continue
                sub = nums[i:i+length]
                if 68 <= sum(sub[:5]) <= 115:
                    best = sub[:5]
                    break
            if best:
                break

        if not best:
            continue

        ref, lab, con, lib, grn = best

        polls.append({
            'pollster': pollster,
            'client': cells[1][:40] if len(cells) > 1 else '',
            'date': date_str,
            'sort_key': sort_key,
            'n': n or 0,
            'ref': ref, 'lab': lab, 'con': con, 'lib': lib, 'grn': grn,
            'src': POLLSTER_SRCS.get(pollster, ''),
        })

    # Deduplicate newest-first
    seen, unique = set(), []
    for p in sorted(polls, key=lambda x: -x['sort_key']):
        k = (p['pollster'], p['sort_key'])
        if k not in seen:
            seen.add(k)
            unique.append(p)

    return unique[:30]

def build_monthly_history(polls):
    by_month = defaultdict(list)
    for p in polls:
        by_month[p['sort_key'] // 100].append(p)
    labels, ref_a, lab_a, con_a, grn_a, lib_a = [], [], [], [], [], []
    def avg(lst, k): return round(sum(x[k] for x in lst) / len(lst), 1)
    for ym in sorted(by_month):
        mo = ym % 100
        labels.append(f"{MON_ABBR[mo]} {str(ym//100)[2:]}")
        g = by_month[ym]
        ref_a.append(avg(g,'ref')); lab_a.append(avg(g,'lab'))
        con_a.append(avg(g,'con')); grn_a.append(avg(g,'grn'))
        lib_a.append(avg(g,'lib'))
    return {'labels':labels,'ref':ref_a,'lab':lab_a,'con':con_a,'grn':grn_a,'lib':lib_a}

def parse_leader_approval(wikitext):
    results = {}
    wikitext = wikitext.replace('||', '\n|')
    parts = re.split(r'\n={2,3}\s*([^=\n]+?)\s*={2,3}\n', wikitext)

    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i+1] if i+1 < len(parts) else ''

        matched = None
        for name in LEADER_MAP:
            last = name.split()[-1]
            if last.lower() in heading.lower() or name.lower() in heading.lower():
                matched = name
                break
        if not matched:
            continue

        rows = []
        for row in re.split(r'\n\s*\|-+[^\n]*\n', body):
            raw_cells = re.findall(r'^\|([^\n|!][^\n]*)', row, re.MULTILINE)
            cells = [strip_wiki(c).strip() for c in raw_cells if strip_wiki(c).strip()]
            if len(cells) < 3:
                continue

            sort_key, date_str = None, None
            for c in cells[:4]:
                sk, ds = parse_date(c)
                if sk and sk > 20240700:
                    sort_key, date_str = sk, ds
                    break
            if not sort_key:
                continue

            pollster = ''
            for c in cells[:5]:
                for known in POLLSTER_SRCS:
                    if known.lower() in c.lower():
                        pollster = known
                        break
                if pollster:
                    break

            nums = [v for c in cells if (v := clean_num(c)) is not None and 5 <= v <= 90]
            if len(nums) < 2:
                continue

            rows.append({
                'sort_key': sort_key, 'date': date_str,
                'pollster': pollster,
                'approve': nums[0], 'disapprove': nums[1],
            })

        if not rows:
            continue

        yg = [r for r in rows if r['pollster'] == 'YouGov']
        best = sorted(yg or rows, key=lambda x: -x['sort_key'])[0]
        src = f"YouGov · {best['date']}" if best['pollster'] == 'YouGov' else f"{best['pollster']} · {best['date']}"

        results[matched] = {
            'name': matched,
            'approve': best['approve'],
            'disapprove': best['disapprove'],
            'net': best['approve'] - best['disapprove'],
            'src': src,
        }
        print(f"  {matched}: {best['approve']}%/{best['disapprove']}% ({src})", file=sys.stderr)

    return list(results.values())

def main():
    print("Fetching voting intention...", file=sys.stderr)
    vi_wikitext = fetch_wikitext(VI_PAGE)
    print(f"  Wikitext length: {len(vi_wikitext)} chars", file=sys.stderr)

    polls = parse_vi_polls(vi_wikitext)
    print(f"  {len(polls)} polls parsed", file=sys.stderr)

    if not polls:
        # Debug: print first 2000 chars of wikitext to help diagnose
        print("DEBUG wikitext sample:\n" + vi_wikitext[:2000], file=sys.stderr)
        print("ERROR: no polls parsed — aborting", file=sys.stderr)
        sys.exit(1)

    monthly = build_monthly_history(polls)
    print(f"  {len(monthly['labels'])} monthly averages", file=sys.stderr)

    print("Fetching leader approval...", file=sys.stderr)
    try:
        la_wikitext = fetch_wikitext(LA_PAGE)
        leader_approval = parse_leader_approval(la_wikitext)
        print(f"  {len(leader_approval)} leaders parsed", file=sys.stderr)
    except Exception as e:
        print(f"  WARNING: {e}", file=sys.stderr)
        leader_approval = []

    for p in polls:
        p.pop('sort_key', None)

    print(json.dumps({
        'generated': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'monthly_history': monthly,
        'recent_polls': polls[:10],
        'leader_approval': leader_approval,
    }, indent=2))

    print(f"\nDone: {len(polls)} polls · {len(monthly['labels'])} months · {len(leader_approval)} leaders", file=sys.stderr)

if __name__ == '__main__':
    main()

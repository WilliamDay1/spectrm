#!/usr/bin/env python3
"""
fetch_economic.py - Fetches ONS, BoE, NHS data. Runs daily via GitHub Actions.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, date

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA_FILE = os.path.join(REPO_ROOT, 'data', 'economic.json')

def fetch_json(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Spectrm/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  WARN: {url}: {e}", file=sys.stderr)
        return {}

def ons_latest(dataset, series):
    url = f"https://api.ons.gov.uk/v2/datasets/{dataset}/timeseries/{series}/data"
    data = fetch_json(url)
    months = data.get('months', [])
    if not months:
        return None
    try:
        return float(months[-1].get('value', '').replace(',', ''))
    except (ValueError, AttributeError):
        return None

def load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save(data):
    data.setdefault('_meta', {})['updated'] = date.today().isoformat()
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Saved {DATA_FILE}")

def main():
    print(f"fetch_economic.py — {datetime.now().isoformat()}")
    current = load()
    kpis = current.setdefault('kpis', {})

    # CPI from ONS
    print("Fetching CPI (ONS)...")
    cpi = ons_latest('mm23', 'D7G7')
    if cpi is not None:
        print(f"  CPI: {cpi}")
        kpis.setdefault('cpi', {})['value'] = cpi
    else:
        print("  CPI: unavailable, keeping existing")

    # Unemployment from ONS
    print("Fetching unemployment (ONS)...")
    unemp = ons_latest('lms', 'MGSX')
    if unemp is not None:
        print(f"  Unemployment: {unemp}")
        kpis.setdefault('unemployment', {})['value'] = unemp
    else:
        print("  Unemployment: unavailable, keeping existing")

    # Update chart history last points
    h = current.get('chart_history', {})
    if cpi and 'cpi' in h and h['cpi']:
        h['cpi'][-1] = round(cpi, 1)
    if unemp and 'unemployment' in h and h['unemployment']:
        h['unemployment'][-1] = round(unemp, 1)
    current['chart_history'] = h

    save(current)
    print("Done.")

if __name__ == '__main__':
    main()

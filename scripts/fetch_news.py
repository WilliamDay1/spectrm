#!/usr/bin/env python3
"""
fetch_news.py - Fetches BBC/Guardian/Reuters RSS feeds. Runs daily.
"""
import json, os, sys, re, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA_FILE = os.path.join(REPO_ROOT, 'data', 'news.json')

FEEDS = [
    {'name': 'BBC Politics',         'url': 'https://feeds.bbci.co.uk/news/politics/rss.xml'},
    {'name': 'The Guardian Politics', 'url': 'https://www.theguardian.com/politics/rss'},
    {'name': 'Sky News Politics',     'url': 'https://feeds.skynews.com/feeds/rss/politics.xml'},
]

TAG_RULES = [
    (['burnham','starmer','labour leader','leadership contest'], 'Leadership', 'ldr'),
    (['reform uk','farage'], 'Reform', 'tc-ref'),
    (['nhs','health service','hospital','waiting list'], 'NHS', 'tc-h'),
    (['inflation','economy','gdp','bank of england','interest rate','budget'], 'Economy', 'tc-e'),
    (['ukraine','nato','defence','military'], 'Defence', 'tc-d'),
    (['gaza','israel','palestine'], 'Gaza', 'tc-f'),
    (['immigration','asylum','migration','border'], 'Immigration', 'tc-c'),
    (['housing','rent','mortgage'], 'Housing', 'tc-c'),
    (['climate','net zero','energy'], 'Energy', 'tc-e'),
    (['scotland','snp','wales'], 'Devolution', 'tc-c'),
    (['election','by-election','polling','poll'], 'Election', 'tc-c'),
]

def fetch_feed(feed):
    items = []
    try:
        req = urllib.request.Request(feed['url'], headers={'User-Agent': 'Spectrm/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())
        for entry in root.findall('.//item')[:15]:
            title_el = entry.find('title')
            link_el  = entry.find('link')
            pub_el   = entry.find('pubDate')
            title = title_el.text.strip() if title_el is not None and title_el.text else ''
            # Strip "Source | Section | " prefixes
            title = re.sub(r'^[^|]+\|[^|]+\|\s*', '', title).strip()
            link  = link_el.text.strip() if link_el is not None and link_el.text else ''
            pub_dt = None
            pub_str = ''
            if pub_el is not None and pub_el.text:
                try:
                    pub_dt = parsedate_to_datetime(pub_el.text)
                    pub_str = pub_dt.strftime('%-d %b %Y')
                except Exception:
                    pub_str = ''
            if len(title) > 10:
                items.append({'title': title, 'url': link, 'pub_str': pub_str,
                               'pub_dt': pub_dt, 'source': feed['name']})
    except Exception as e:
        print(f"  WARN: {feed['name']}: {e}", file=sys.stderr)
    return items

def categorise(title):
    lower = title.lower()
    for keywords, tag, cls in TAG_RULES:
        if any(kw in lower for kw in keywords):
            return tag, cls
    return 'Politics', 'tc-c'

def is_relevant(title):
    skip = ['sport','football','cricket','tennis','rugby','celebrity',
            'film','movie','strictly','weather','recipe','fashion']
    lower = title.lower()
    return not any(w in lower for w in skip)

def main():
    print(f"fetch_news.py — {datetime.now().isoformat()}")
    all_items = []
    for feed in FEEDS:
        print(f"  Fetching {feed['name']}...")
        items = fetch_feed(feed)
        print(f"    {len(items)} items")
        all_items.extend(items)

    all_items = [i for i in all_items if is_relevant(i['title'])]
    all_items.sort(key=lambda x: x.get('pub_dt') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    # Deduplicate
    seen, deduped = [], []
    for item in all_items:
        key = ' '.join(item['title'].lower().split()[:6])
        if key not in seen:
            seen.append(key)
            deduped.append(item)

    if not deduped:
        print("WARN: No headlines — keeping existing data", file=sys.stderr)
        sys.exit(0)

    headlines = []
    for i, item in enumerate(deduped[:10]):
        tag, cls = categorise(item['title'])
        headlines.append({
            'id': str(i + 1),
            'tag': tag, 'tag_class': cls,
            'headline': item['title'],
            'date': item['pub_str'],
            'source': item['source'],
            'url': item['url'],
        })

    output = {
        '_meta': {
            'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'update_frequency': 'daily',
        },
        'headlines': headlines,
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Saved {len(headlines)} headlines")
    for h in headlines:
        print(f"  [{h['tag']}] {h['headline'][:70]}")

if __name__ == '__main__':
    main()

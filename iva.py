#!/usr/bin/env python3
"""Download Singapore's monthly visitor numbers (Singapore Tourism Board, via SingStat) into iva.json.

Run daily by .github/workflows/news.yml alongside news.py (free, no keys, no AI). SingStat's tables
get each month's numbers about a week after STB announces them, so the file changes about once a month.
The map's Insights page reads iva.json when it opens.

Tables used:
  M550001  arrivals by place of residence (total, regions, every country)
  M550071  arrivals by length of stay  -> overnight visitors = total - "Under 1 Day"
  M550281  visitor days                -> average length of stay = visitor days / total arrivals (STB's own method)
"""
import json, urllib.request
from pathlib import Path

API = 'https://tablebuilder.singstat.gov.sg/api/table/tabledata/{}?limit=5000&offset={}'   # pages of 5,000 data points (not rows)
MONTHS = 25   # enough for this month vs the same month last year, and both years' Jan-to-date
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
OUT = Path(__file__).parent / 'iva.json'

def table(tid):
    """Every row of a SingStat table; it sends at most 5,000 numbers per request, so read page by page."""
    rows, meta, off = {}, None, 0
    while True:
        req = urllib.request.Request(API.format(tid, off), headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})   # needs an Accept header or it answers 403
        data = json.loads(urllib.request.urlopen(req, timeout=90).read())['Data']
        meta = meta or data
        if not data['row']: break
        for r in data['row']:   # a row can be split across two pages: stitch its months back together
            rows.setdefault(r['seriesNo'], {**r, 'columns': []})['columns'] += r['columns']
        off += 5000
        if off > 200000: break
    meta['row'] = sorted(rows.values(), key=lambda r: [int(x) for x in r['seriesNo'].split('.')])
    return meta

def months(row):
    cols = [c for c in row['columns'] if str(c.get('value', '')).replace('.', '').isdigit()]
    return {c['key']: int(float(c['value'])) for c in cols[-MONTHS:]}

arr = table('M550001')
series, regions, countries = {}, [], []
for row in arr['row']:
    name, depth = row['rowText'].strip(), row['seriesNo'].count('.')
    if depth == 0: series['Total'] = months(row)
    elif name.startswith('Other Markets'): continue
    elif depth == 1: regions.append(name); series[name] = months(row)
    elif depth == 2 and row['columns'] and row['columns'][-1]['key'] == arr['row'][0]['columns'][-1]['key']:   # skip countries no longer reported
        countries.append(name); series[name] = months(row)
need = ['China', 'Hong Kong SAR', 'Japan', 'South Korea', 'Thailand', 'Malaysia', 'Indonesia', 'Philippines', 'Vietnam', 'India']
if 'Total' not in series or any(k not in series for k in need):
    raise SystemExit('SingStat table changed shape, not saving')
latest = max(series['Total'], key=lambda k: int(k[:4]) * 12 + MON.index(k[5:]))

extra = {}
try:   # overnight visitors + average stay; never block the main numbers
    los = {r['rowText'].strip(): months(r) for r in table('M550071')['row']}
    tot, day = los.get('Total International Visitor Arrivals', {}), los.get('Under 1 Day', {})
    extra['overnight'] = {k: tot[k] - day[k] for k in tot if k in day}
    vd = months(table('M550281')['row'][0])
    extra['avgStay'] = {k: round(vd[k] / series['Total'][k], 2) for k in vd if series['Total'].get(k)}
except Exception as e:
    print('extra stats skipped:', e)

OUT.write_text(json.dumps({'source': 'Singapore Tourism Board via SingStat (tables M550001, M550071, M550281)', 'updated': arr.get('dataLastUpdated'),
                           'latest': latest, 'regions': regions, 'countries': countries, 'series': series, 'extra': extra}, ensure_ascii=False, indent=1))
print(f'latest month {latest}, {len(countries)} countries, extra: {list(extra)}')

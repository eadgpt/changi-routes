#!/usr/bin/env python3
"""Collect Changi route/airline headlines from free news feeds into news.json.

Run once a day by .github/workflows/news.yml (no AI, no keys). Keeps what it
found on earlier days, so the list builds up even though each feed only shows
its last few stories. The map's Insights page reads news.json when it opens.
"""
import json, re, html, urllib.request, email.utils
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

FEEDS = [
    ('CNA', 'https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416'),
    ('Mainly Miles', 'https://mainlymiles.com/feed/'),
    ('AeroRoutes', 'https://aeroroutes.com/eng?format=rss'),
    ('AeroTime', 'https://www.aerotime.aero/feed'),
    ('Business Traveller', 'https://www.businesstraveller.com/feed/'),
    ('TTG Asia', 'https://www.ttgasia.com/feed/'),
    ('Aviation A2Z', 'https://aviationa2z.com/index.php/feed/'),
    ('Straits Times', 'https://www.straitstimes.com/news/singapore/rss.xml'),
    ('Straits Times', 'https://www.straitstimes.com/news/business/rss.xml'),
    ('Business Times', 'https://www.businesstimes.com.sg/rss/transport'),
    ('The Edge Singapore', 'https://www.theedgesingapore.com/rss.xml'),
    ('FlightGlobal', 'https://www.flightglobal.com/rss'),
]
# the headline must name Singapore/Changi AND be about flying; judged on the headline only
PLACE = re.compile(r'\b(changi|singapore|scoot|sia)\b', re.I)
AVIA = re.compile(r'\b(scoot|passengers?|airlines?|flights?|routes?|airports?|terminals?|carriers?|aircraft|jets?|aviation|air travel|levy)\b', re.I)
SKIP = re.compile(r'\b(krisflyer|miles|points|credit card|citi|lounge|award|sale|promo\w*|deals?|review|seats?|cabins?|first class|business class|priority pass|mro|prison|jail|court|charged|crash\w*|collid\w*|drugs?|smuggl\w*|arrested|beach'
                  # not about routes or airlines: crime and customs, shows and events, staff stories, on-board extras, fuel, far-away conflicts
                  r'|caught|stopped at|seized|trading cards|probes?|offences?|fined|ordered to pay|complaint|dies|died|cancer|steward\w*|attendants?|shoes|sandals|uniforms?'
                  r'|pokemon|pikachu|themed|schools?|spotlight|puppet\w*|jewel|travel fair|discount\w*|jobs|hiring'
                  r'|dining|dish(?:es)?|meals?|menus?|serviceware|chinaware|entertainment|krisworld|premium economy|closer look|prizes?|best airline'
                  r'|saf|sustainable aviation|jet fuel|maintenance|repair|rts|condemns?|houthi|attacks?|emergency landing|disruptive)\b', re.I)
def wanted(title): return bool(PLACE.search(title) and AVIA.search(title) and not SKIP.search(title))
COUNTRIES = {'China': r"china|chinese|hainan|sichuan|beijing|shanghai|guangzhou|shenzhen|chengdu|chongqing|xiamen|hangzhou|urumqi|hohhot|haikou|sanya|kunming|wuhan|xi'?an|nanjing|qingdao|changsha|fuzhou|tianjin|harbin|shenyang|zhengzhou|nanning|guiyang|ningbo|jinan|hefei|lhasa",
             'Hong Kong': r'hong kong|macau|macao|cathay', 'Japan': r'japan|tokyo|osaka|nagoya|fukuoka|sapporo|okinawa|hiroshima|sendai|kagoshima|haneda|narita|\bana\b|\bjal\b',
             'South Korea': r'korea|seoul|busan|jeju|incheon|gimpo|daegu|cheongju', 'Thailand': r'thailand|thai|bangkok|phuket|chiang mai|chiang rai|krabi|koh samui|hat yai|pattaya',
             'Malaysia': r'malaysia|kuala lumpur|\bkl\b|penang|sabah|sarawak|johor|langkawi|kuching|kota kinabalu|ipoh|malacca|subang|firefly|batik air malaysia',
             'Indonesia': r'indonesia|jakarta|bali|denpasar|surabaya|medan|batam|aceh|lombok|makassar|manado|yogyakarta|bandung|garuda|transnusa|citilink',
             'Philippines': r'philippine|manila|cebu|clark|davao|iloilo|boracay|caticlan', 'Vietnam': r'vietnam|vietjet|hanoi|ho chi minh|da nang|hai phong|da lat|phu quoc|nha trang|hue\b|can tho',
             'India': r'india\b|indian (?!ocean)|indigo|air india|delhi|mumbai|chennai|bengaluru|bangalore|hyderabad|kolkata|kochi|ahmedabad|amritsar|coimbatore|trichy|tiruchirappalli|thiruvananthapuram|visakhapatnam|vijayawada|guwahati|lucknow|jaipur|goa\b|pune\b'}
def tag(text): return [c for c, rx in COUNTRIES.items() if re.search(r'\b(?:' + rx + ')', text, re.I)]
# the same story from several feeds: keep the first one found, drop later look-alikes from the same few days
STOP = set('a an the to of in on for and with from its is as at by after into over up new will be this that these it s'.split())
SAME = {'sia': 'singapore airline', 'february': 'feb', 'cancellation': 'cancel', 'cancels': 'cancel', 'flights': 'flight', 'airlines': 'airline'}
def words(title):
    t = ' '.join(SAME.get(w, w) for w in re.findall(r"[a-z0-9]+", title.lower()))
    return {w[:-1] if len(w) > 4 and w.endswith('s') else w for w in t.split()} - STOP
def near(a, b):
    if abs((datetime.strptime(a['date'], '%Y-%m-%d') - datetime.strptime(b['date'], '%Y-%m-%d')).days) > 4: return False
    x, y = words(a['title']), words(b['title'])
    return len(x & y) / max(1, len(x | y)) >= 0.5
def no_repeats(items):
    kept = []
    for i in sorted(items, key=lambda i: i['date']):   # oldest first, so the first report of a story stays
        if not any(near(i, k) for k in kept): kept.append(i)
    return kept
KEEP_DAYS, KEEP_MAX = 120, 40
OUT = Path(__file__).parent / 'news.json'

def text(el, tag):
    x = el.find(tag)
    return html.unescape(re.sub(r'<[^>]+>', ' ', x.text or '')).strip() if x is not None and x.text else ''

def fetch(name, url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (changi-routes news bot)'})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    for it in root.iter('item'):
        title, link, desc = text(it, 'title'), text(it, 'link'), text(it, 'description')[:600]
        try: when = email.utils.parsedate_to_datetime(text(it, 'pubDate')).astimezone(timezone.utc)
        except Exception: when = datetime.now(timezone.utc)
        blob = f'{title} {desc}'
        if not wanted(title):
            continue
        tags = tag(blob)
        yield {'title': title, 'url': link, 'src': name, 'date': when.strftime('%Y-%m-%d'), 'tags': tags}

old = [i for i in (json.loads(OUT.read_text())['items'] if OUT.exists() else []) if wanted(i['title'])]   # re-check old ones when the rules change
for i in old: i['tags'] = sorted(set(i.get('tags', [])) | set(tag(i['title'])))   # new countries tag old stories too
seen = {i['url'] for i in old}
new = []
for name, url in FEEDS:
    try:
        for item in fetch(name, url):
            if item['url'] not in seen:
                seen.add(item['url']); new.append(item)
    except Exception as e:   # one broken feed never stops the rest
        print(f'skip {name}: {e}')
cut = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d')
items = sorted(no_repeats([i for i in old + new if i['date'] >= cut]), key=lambda i: i['date'], reverse=True)[:KEEP_MAX]
OUT.write_text(json.dumps({'updated': datetime.now(timezone.utc).strftime('%Y-%m-%d'), 'items': items}, ensure_ascii=False, indent=1))
print(f'{len(new)} new, {len(items)} kept')

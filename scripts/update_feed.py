"""Pull WoW: Forever news from public RSS/Atom feeds into feed.json. Standard library only.
Runs hourly from GitHub Actions. Keeps a rolling archive so older stories stay on the site."""
import json, re, html, pathlib, datetime, urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "feed.json"
UA = "ForeverFieldGuide/1.0 (fan guide; GitHub Actions)"

# (url, category, forever_only_feed). General feeds are filtered to stories that mention Forever.
FEEDS = [
    ("https://news.blizzard.com/en-us/feed/world-of-warcraft", "Official", False),
    ("https://www.wowhead.com/forever/news/rss", "Community", True),
    ("https://www.wowhead.com/news/rss/all", "Community", False),
    ("https://www.warcrafttavern.com/forever/news/feed/", "Community", True),
    ("https://www.warcrafttavern.com/feed/", "Community", False),
]
KEYWORDS = re.compile(r"\bforever\b|skyborne|zephras|shen'?dralas|riverglades", re.I)


def text(el, *names):
    for n in names:
        f = el.find(n)
        if f is not None:
            return (f.text or f.get("href") or "").strip()
    return ""


def clean(s, limit=220):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:limit].rsplit(" ", 1)[0] + "…") if len(s) > limit else s


def iso(d):
    try:
        return parsedate_to_datetime(d).date().isoformat()
    except Exception:
        m = re.match(r"\d{4}-\d{2}-\d{2}", d or "")
        return m.group(0) if m else datetime.date.today().isoformat()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, text/xml"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


ATOM = "{http://www.w3.org/2005/Atom}"
existing = []
if OUT.exists():
    try:
        existing = json.loads(OUT.read_text()).get("news", [])
    except Exception:
        existing = []
seen = {n["url"] for n in existing if n.get("url")}
added = 0
for url, cat, forever_only in FEEDS:
    try:
        root = ET.fromstring(fetch(url))
    except Exception as e:
        print(f"skip {url}: {e}")
        continue
    entries = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    for it in entries:
        title = clean(text(it, "title", f"{ATOM}title"), 160)
        link = text(it, "link", f"{ATOM}link")
        desc = text(it, "description", f"{ATOM}summary", f"{ATOM}content")
        cats = " ".join((c.text or c.get("term") or "") for c in it.findall("category") + it.findall(f"{ATOM}category"))
        if not title or not link or link in seen:
            continue
        if not forever_only and not KEYWORDS.search(f"{title} {desc} {cats} {link}"):
            continue
        if "hotfix" in title.lower():
            category = "Hotfix"
        elif "patch" in title.lower():
            category = "Patch"
        else:
            category = cat
        existing.append({"date": iso(text(it, "pubDate", f"{ATOM}published", f"{ATOM}updated")),
                         "title": title, "summary": clean(desc), "category": category, "url": link, "auto": True})
        seen.add(link)
        added += 1

existing.sort(key=lambda n: n.get("date", ""), reverse=True)
OUT.write_text(json.dumps({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                           "news": existing[:400]}, ensure_ascii=False, indent=0))
print(f"feed: +{added}, total {len(existing[:400])}")

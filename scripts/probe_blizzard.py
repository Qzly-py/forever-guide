"""One-off check: which Blizzard Game Data API endpoints serve WoW: Forever data, and what they look like.
Prints status, counts and a short sample of each. Never prints the key."""
import os, sys, json, base64, urllib.request, urllib.parse, urllib.error

REGION = os.environ.get("BLIZZARD_REGION", "eu")
LOCALE = "en_GB" if REGION == "eu" else "en_US"
API = f"https://{REGION}.api.blizzard.com"
CID, SECRET = os.environ.get("BLIZZARD_CLIENT_ID", ""), os.environ.get("BLIZZARD_CLIENT_SECRET", "")
if not CID or not SECRET:
    sys.exit("no key")

body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
auth = base64.b64encode(f"{CID}:{SECRET}".encode()).decode()
req = urllib.request.Request("https://oauth.battle.net/token", data=body,
                             headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
TOKEN = json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


def get(path, ns="static", **params):
    params = {"namespace": f"{ns}-forever-{REGION}", "locale": LOCALE, **params}
    url = f"{API}{path}?{urllib.parse.urlencode(params, safe='[],')}"
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"}), timeout=60)
        return 200, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return str(e), None


def short(v, n=700):
    s = json.dumps(v, ensure_ascii=False)
    return s[:n] + ("…" if len(s) > n else "")


def first_list(d):
    for k, v in (d or {}).items():
        if isinstance(v, list) and v:
            return k, v
    return None, []


INDEXES = """mount pet pet-ability creature-family creature-type quest quest/category quest/area quest/type
journal-instance journal-encounter journal-expansion profession reputation-faction reputation-tiers
playable-class playable-race playable-specialization talent-tree talent pvp-talent achievement achievement-category
toy title item-set item-class heirloom pvp-season pvp-tier power-type region media guild-crest""".split()

for name in INDEXES:
    code, d = get(f"/data/wow/{name}/index")
    key, lst = first_list(d)
    print(f"\n### {name}/index -> {code}  list={key} count={len(lst)}")
    if d and not lst:
        print("  keys:", list(d.keys())[:15])
    if lst:
        print("  first:", short(lst[0], 300))
        ref = lst[0]
        href = (ref.get("key") or {}).get("href", "")
        if href:
            path = urllib.parse.urlparse(href).path
            c2, det = get(path)
            print(f"  detail {path} -> {c2}")
            if det:
                print("  ", short({k: v for k, v in det.items() if k != "_links"}, 1500))

for name, params in [("creature", {"orderby": "id", "_pageSize": 5, "_page": 1}),
                     ("journal-encounter", {"orderby": "id", "_pageSize": 3, "_page": 1}),
                     ("spell", {"orderby": "id", "_pageSize": 3, "_page": 1, "name.en_US": "Bite"}),
                     ("media", {"_pageSize": 3, "_page": 1, "tags": "item"}),
                     ("mount", {"_pageSize": 3, "_page": 1}),
                     ("item", {"orderby": "id", "_pageSize": 2, "_page": 1, "id": "[18000,]"})]:
    code, d = get(f"/data/wow/search/{name}", **params)
    rows = (d or {}).get("results", [])
    print(f"\n### search/{name} -> {code} pageCount={(d or {}).get('pageCount')} rows={len(rows)}")
    for r in rows[:2]:
        print("  ", short(r.get("data"), 1200))

# Creature detail: does it say tameable / family / zone?
code, d = get("/data/wow/search/creature", orderby="id", _pageSize=200, _page=1, **{"family.name.en_US": "Wolf"})
rows = (d or {}).get("results", [])
print(f"\n### search/creature family=Wolf -> {code} rows={len(rows)} pageCount={(d or {}).get('pageCount')}")
for r in rows[:3]:
    print("  ", short(r.get("data"), 800))
if rows:
    cid = rows[0]["data"]["id"]
    c2, det = get(f"/data/wow/creature/{cid}")
    print(f"  creature/{cid} -> {c2}:", short(det, 1500))

# Item detail sample (stats, sources)
for iid in (19019, 18832, 6948):
    c, det = get(f"/data/wow/item/{iid}")
    print(f"\n### item/{iid} -> {c}:", short({k: v for k, v in (det or {}).items() if k != "_links"}, 2500))

# Dynamic namespace (realms)
code, d = get("/data/wow/realm/index", ns="dynamic")
key, lst = first_list(d)
print(f"\n### dynamic realm/index -> {code} count={len(lst)} sample={short(lst[:3], 400)}")

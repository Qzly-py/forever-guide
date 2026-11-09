"""Download every WoW: Forever item (and any mounts/pets Blizzard exposes) from the official
Blizzard Game Data API into items.json. Standard library only. Needs repository secrets
BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET; exits quietly without them."""
import os, sys, json, time, base64, pathlib, datetime, urllib.request, urllib.parse, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "items.json"
REGION = os.environ.get("BLIZZARD_REGION", "eu")
LOCALE = "en_GB" if REGION == "eu" else "en_US"
NS = f"static-forever-{REGION}"
API = f"https://{REGION}.api.blizzard.com"
CID, SECRET = os.environ.get("BLIZZARD_CLIENT_ID", ""), os.environ.get("BLIZZARD_CLIENT_SECRET", "")
if not CID or not SECRET:
    print("No Blizzard key set yet; skipping item update.")
    sys.exit(0)


def token():
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    auth = base64.b64encode(f"{CID}:{SECRET}".encode()).decode()
    req = urllib.request.Request("https://oauth.battle.net/token", data=body,
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


TOKEN = token()


def get(path, **params):
    params = {"namespace": NS, "locale": LOCALE, **params}
    url = f"{API}{path}?{urllib.parse.urlencode(params, safe='[],')}"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            print(f"{path}: HTTP {e.code}")
            return None
        except Exception as e:
            print(f"{path}: {e}")
            time.sleep(2 ** attempt)
    return None


def loc(v):
    if isinstance(v, dict):
        return v.get(LOCALE) or v.get("en_US") or v.get("en_GB") or next(iter(v.values()), "")
    return v or ""


def money(c):
    if not c:
        return ""
    g, s, cp = c // 10000, (c // 100) % 100, c % 100
    return " ".join(p for p in (f"{g}g" if g else "", f"{s}s" if s else "", f"{cp}c" if cp else "") if p)


# Items: page through the search endpoint by id ranges (search caps each query, so walk the ids).
items, last_id = [], 0
while True:
    res = get("/data/wow/search/item", orderby="id", _pageSize=1000, _page=1, id=f"[{last_id + 1},]")
    rows = (res or {}).get("results", [])
    if not rows:
        break
    for row in rows:
        d = row.get("data", {})
        items.append({
            "id": d.get("id"),
            "name": loc(d.get("name")),
            "quality": loc((d.get("quality") or {}).get("name")).title(),
            "level": d.get("level") or 0,
            "reqLevel": d.get("required_level") or "",
            "slot": loc((d.get("inventory_type") or {}).get("name")) if (d.get("inventory_type") or {}).get("type") != "NON_EQUIP" else "",
            "itemClass": loc((d.get("item_class") or {}).get("name")),
            "subclass": loc((d.get("item_subclass") or {}).get("name")),
            "sellPrice": money(d.get("sell_price") or 0),
        })
    last_id = max(r.get("data", {}).get("id", last_id) for r in rows)
    print(f"items so far: {len(items)} (up to id {last_id})")
    time.sleep(0.2)

# Mounts and pets, if Blizzard serves these indexes for Forever (falls back to nothing if not).
extra = {}
for key, path, field in (("mounts", "/data/wow/mount/index", "mounts"), ("pets", "/data/wow/pet/index", "pets")):
    res = get(path)
    if res and res.get(field):
        extra[key] = [{"name": loc(m.get("name")), "id": m.get("id")} for m in res[field]]
        print(f"{key}: {len(extra[key])}")

if not items and OUT.exists():
    print("API returned no items; keeping the previous items.json")
    sys.exit(0)
OUT.write_text(json.dumps({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                           "items": [i for i in items if i["name"]], **extra}, ensure_ascii=False, separators=(",", ":")))
print(f"wrote {len(items)} items")

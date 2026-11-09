"""Download everything Blizzard's Game Data API serves for WoW: Forever into items.json and live/*.json.
Standard library only. Needs repository secrets BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET; exits quietly
without them. Detail lookups are cached in the previous output files, so daily runs only fetch what's new;
a full refresh happens on Mondays (or with FULL_REFRESH=1)."""
import os, sys, json, time, base64, pathlib, datetime, threading, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = ROOT / "live"
LIVE.mkdir(exist_ok=True)
REGION = os.environ.get("BLIZZARD_REGION", "eu")
LOCALE = "en_GB" if REGION == "eu" else "en_US"
NS = f"static-forever-{REGION}"
API = f"https://{REGION}.api.blizzard.com"
CID, SECRET = os.environ.get("BLIZZARD_CLIENT_ID", ""), os.environ.get("BLIZZARD_CLIENT_SECRET", "")
if not CID or not SECRET:
    print("No Blizzard key set yet; skipping Blizzard update.")
    sys.exit(0)
NOW = datetime.datetime.now(datetime.timezone.utc)
FULL = os.environ.get("FULL_REFRESH") == "1" or NOW.weekday() == 0


def token():
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    auth = base64.b64encode(f"{CID}:{SECRET}".encode()).decode()
    req = urllib.request.Request("https://oauth.battle.net/token", data=body,
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


TOKEN = token()
_calls, _lock = [0], threading.Lock()


def get(path, **params):
    params = {"namespace": NS, "locale": LOCALE, **params}
    url = f"{API}{path}?{urllib.parse.urlencode(params, safe='[],')}"
    for attempt in range(5):
        with _lock:
            _calls[0] += 1
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            if e.code != 404:
                print(f"{path}: HTTP {e.code}")
            return None
        except Exception as e:
            print(f"{path}: {e}")
            time.sleep(2 ** attempt)
    return None


def loc(v):
    if isinstance(v, dict):
        return v.get(LOCALE) or v.get("en_US") or v.get("en_GB") or next((x for x in v.values() if isinstance(x, str)), "")
    return v if isinstance(v, str) else ("" if v is None else str(v))


def nm(v):
    """Name of a linked object ({name: ...}) or a plain value."""
    return loc(v.get("name")) if isinstance(v, dict) else loc(v)


def money(c):
    if not c:
        return ""
    g, s, cp = c // 10000, (c // 100) % 100, c % 100
    return " ".join(p for p in (f"{g}g" if g else "", f"{s}s" if s else "", f"{cp}c" if cp else "") if p)


def clean(d):
    """Drop empty fields so files stay small."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {}, False)}


def pmap(fn, xs, workers=8):
    xs = list(xs)
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, xs))


def load(name):
    p = LIVE / f"{name}.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def cached(name, key="entries"):
    """id -> entry from the previous run (empty on a full refresh)."""
    if FULL:
        return {}
    return {e["id"]: e for e in load(name).get(key, []) if isinstance(e, dict) and e.get("id") is not None}


def save(name, entries, **extra):
    entries = [e for e in entries if e and e.get("name")]
    if not entries and (LIVE / f"{name}.json").exists():
        print(f"{name}: API returned nothing; keeping previous file")
        return
    (LIVE / f"{name}.json").write_text(json.dumps({"updated": NOW.isoformat(timespec="seconds"), "entries": entries, **extra},
                                                  ensure_ascii=False, separators=(",", ":")))
    print(f"{name}: {len(entries)}")


def walk(kind, keep=lambda d: True, **params):
    """Every result of a search endpoint, walking id ranges (search caps each query)."""
    out, last = [], 0
    while True:
        res = get(f"/data/wow/search/{kind}", orderby="id", _pageSize=1000, _page=1, id=f"[{last + 1},]", **params)
        rows = (res or {}).get("results", [])
        if not rows:
            break
        out += [r["data"] for r in rows if keep(r.get("data", {}))]
        last = max(r.get("data", {}).get("id", last) for r in rows)
        time.sleep(0.1)
    return out


def section(fn):
    """Run one section; a failure in one never stops the others."""
    t = time.time()
    try:
        fn()
    except Exception as e:
        print(f"!! {fn.__name__} failed: {e!r}")
    print(f"   ({fn.__name__} {time.time() - t:.0f}s, {_calls[0]} calls so far)")


# ---------------------------------------------------------------- items (+ icons, full stats)
def items():
    prev = {} if FULL else {i["id"]: i for i in (json.loads((ROOT / "items.json").read_text()).get("items", [])
                                                 if (ROOT / "items.json").exists() else []) if i.get("detail")}
    icons = {}
    for m in walk("media", tags="item"):
        a = next((x.get("value") for x in m.get("assets", []) if x.get("key") == "icon"), "")
        if a:
            icons[m["id"]] = a
    print(f"item icons: {len(icons)}")
    rows = walk("item")
    base = {}
    for d in rows:
        inv = d.get("inventory_type") or {}
        base[d["id"]] = clean({
            "id": d.get("id"), "name": loc(d.get("name")), "quality": loc((d.get("quality") or {}).get("name")).title(),
            "level": d.get("level") or 0, "reqLevel": d.get("required_level") or "",
            "slot": loc(inv.get("name")) if inv.get("type") != "NON_EQUIP" else "",
            "itemClass": loc((d.get("item_class") or {}).get("name")), "subclass": loc((d.get("item_subclass") or {}).get("name")),
            "sellPrice": money(d.get("sell_price") or 0), "buyPrice": money(d.get("purchase_price") or 0),
            "icon": icons.get((d.get("media") or {}).get("id") or d.get("id"), ""),
        })
    todo = [i for i in base if i not in prev]
    print(f"items: {len(base)} ({len(todo)} need full details)")

    def detail(iid):
        d = get(f"/data/wow/item/{iid}")
        if not d:
            return iid, None
        p = d.get("preview_item") or {}
        stats = [s.get("display", {}).get("display_string") or f"+{s.get('value')} {nm(s.get('type'))}" for s in p.get("stats", [])]
        w = p.get("weapon") or {}
        lines = [x for x in [
            nm(p.get("binding")), p.get("unique_equipped"),
            (p.get("armor") or {}).get("display", {}).get("display_string"),
            (w.get("damage") or {}).get("display_string"), (w.get("attack_speed") or {}).get("display_string"),
            (w.get("dps") or {}).get("display_string"),
        ] if x] + stats + [s.get("description") for s in p.get("spells", []) if s.get("description")]
        req = p.get("requirements") or {}
        for k in ("playable_classes", "playable_races"):
            if req.get(k):
                lines.append((req[k].get("display_string") or ""))
        if (req.get("skill") or {}).get("display_string"):
            lines.append(req["skill"]["display_string"])
        if (req.get("reputation") or {}).get("display_string"):
            lines.append(req["reputation"]["display_string"])
        st = p.get("set") or {}
        if p.get("description"):
            lines.append(f"“{p['description']}”")
        return iid, clean({"stats": [x for x in lines if x], "set": nm(st.get("item_set")) if st else "",
                           "durability": (p.get("durability") or {}).get("display_string"), "detail": True})

    for iid, extra in pmap(detail, todo):
        if extra:
            prev[iid] = extra
    out = []
    for iid, b in base.items():
        e = dict(b)
        for k, v in (prev.get(iid) or {}).items():
            if k not in ("name",) and v:
                e[k] = v
        out.append(e)
    out = [i for i in out if i.get("name") and not i["name"].startswith(("Monster -", "[PH]"))]
    if not out and (ROOT / "items.json").exists():
        print("API returned no items; keeping the previous items.json")
        return
    (ROOT / "items.json").write_text(json.dumps({"updated": NOW.isoformat(timespec="seconds"), "items": out},
                                                ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {len(out)} items")


# ---------------------------------------------------------------- hunter pets
def hunterpets():
    rows = walk("creature", keep=lambda d: d.get("is_tameable"))
    seen, out = set(), []
    for d in rows:
        name, fam = loc(d.get("name")), loc((d.get("family") or {}).get("name"))
        if not name or name.startswith("[") or (name, fam) in seen:
            continue
        seen.add((name, fam))
        out.append(clean({"id": d["id"], "name": name, "family": fam,
                          "display": (d.get("creature_displays") or [{}])[0].get("id")}))
    save("hunterpets", out, families=[nm(f) for f in (get("/data/wow/creature-family/index") or {}).get("creature_families", [])])


# ---------------------------------------------------------------- mounts / pets / toys / titles / item sets
def mounts():
    old = cached("mounts")
    idx = (get("/data/wow/mount/index") or {}).get("mounts", [])

    def one(m):
        if m["id"] in old:
            return old[m["id"]]
        d = get(f"/data/wow/mount/{m['id']}") or {}
        return clean({"id": m["id"], "name": nm(m), "how": d.get("description") or "", "source": nm(d.get("source")),
                      "faction": nm(d.get("faction")),
                      "requires": ", ".join(nm(x) for x in ((d.get("requirements") or {}).get("classes") or []))})
    save("mounts", [m for m in pmap(one, idx) if not m["name"].startswith("[PH]")])


def pets():
    old = cached("pets")
    idx = (get("/data/wow/pet/index") or {}).get("pets", [])

    def one(m):
        if m["id"] in old:
            return old[m["id"]]
        d = get(f"/data/wow/pet/{m['id']}") or {}
        fac = "Alliance" if d.get("is_alliance_only") else "Horde" if d.get("is_horde_only") else ""
        return clean({"id": m["id"], "name": nm(m), "family": nm(d.get("battle_pet_type")), "how": d.get("description") or "",
                      "source": nm(d.get("source")), "faction": fac, "icon": d.get("icon") or "",
                      "tradable": "Tradable" if d.get("is_tradable") else ""})
    save("pets", pmap(one, idx))


def toys():
    idx = (get("/data/wow/toy/index") or {}).get("toys", [])

    def one(m):
        d = get(f"/data/wow/toy/{m['id']}") or {}
        it = d.get("item") or {}
        return clean({"id": m["id"], "name": nm(m), "kind": "Toy", "source": nm(d.get("source")), "itemId": it.get("id")})
    save("toys", pmap(one, idx))


def titles():
    idx = (get("/data/wow/title/index") or {}).get("titles", [])

    def one(m):
        d = get(f"/data/wow/title/{m['id']}") or {}
        g = d.get("gender_name") or {}
        return clean({"id": m["id"], "name": nm(m), "display": (g.get("male") or "").replace("{name}", "<name>")})
    save("titles", pmap(one, idx))


def itemsets():
    old = cached("itemsets")
    idx = (get("/data/wow/item-set/index") or {}).get("item_sets", [])

    def one(m):
        if m["id"] in old:
            return old[m["id"]]
        d = get(f"/data/wow/item-set/{m['id']}") or {}
        return clean({"id": m["id"], "name": nm(m), "pieces": [nm(i) for i in d.get("items", [])],
                      "bonuses": [f"({e.get('required_count')}) {e.get('display_string')}" for e in d.get("effects", [])]})
    save("itemsets", pmap(one, idx))


# ---------------------------------------------------------------- achievements (Legacy points live here)
def achievements():
    old = cached("achievements")
    idx = (get("/data/wow/achievement/index") or {}).get("achievements", [])
    cats = {}

    def walk_cat(cid, parent=""):
        d = get(f"/data/wow/achievement-category/{cid}") or {}
        name = nm(d)
        for a in d.get("achievements", []):
            cats[a["id"]] = (parent or name, name if parent else "")
        for s in d.get("subcategories", []):
            walk_cat(s["id"], parent or name)
    ci = get("/data/wow/achievement-category/index") or {}
    for c in ci.get("root_categories") or ci.get("categories", []):
        walk_cat(c["id"])

    def one(m):
        if m["id"] in old:
            e = dict(old[m["id"]])
        else:
            d = get(f"/data/wow/achievement/{m['id']}") or {}
            crit = d.get("criteria") or {}
            steps = [c.get("description") for c in crit.get("child_criteria", []) if c.get("description")]
            e = clean({"id": m["id"], "name": nm(m), "how": d.get("description") or "",
                       "reward": d.get("reward_description") or nm((d.get("reward_item") or {})),
                       "points": d.get("points") or "", "accountWide": "Account-wide" if d.get("is_account_wide") else "",
                       "steps": steps, "category": nm(d.get("category"))})
        top, sub = cats.get(m["id"], ("", ""))
        if top:
            e["kind"], e["sub"] = top, sub
        return e
    save("achievements", pmap(one, idx))


# ---------------------------------------------------------------- reputations
def reputations():
    idx = (get("/data/wow/reputation-faction/index") or {}).get("factions", [])
    tiers = {}
    parents = {}

    def one(m):
        d = get(f"/data/wow/reputation-faction/{m['id']}") or {}
        for c in d.get("factions", []):
            parents[c["id"]] = nm(m)
        tid = (d.get("reputation_tiers") or {}).get("id")
        return d, tid
    res = pmap(one, idx)
    for _, tid in res:
        if tid is not None and tid not in tiers:
            t = get(f"/data/wow/reputation-tiers/{tid}") or {}
            tiers[tid] = [f"{x.get('name')} ({x.get('min_value')} to {x.get('max_value')})" for x in t.get("tiers", [])]
    out = []
    for m, (d, tid) in zip(idx, res):
        if d.get("is_header") and not d.get("can_paragon") and d.get("factions") and not d.get("description"):
            continue  # pure group headings like "Horde Forces"
        out.append(clean({"id": m["id"], "name": nm(m), "faction": nm(d.get("player_faction")),
                          "howToRaise": d.get("description") or "", "group": parents.get(m["id"], ""),
                          "standings": tiers.get(tid, [])}))
    save("reputations", out)


# ---------------------------------------------------------------- classes, races, talents
def classes():
    spells = {}

    def spell(sid):
        if sid not in spells:
            d = get(f"/data/wow/spell/{sid}") or {}
            spells[sid] = d.get("description") or ""
        return spells[sid]
    races = []
    for r in (get("/data/wow/playable-race/index") or {}).get("races", []):
        d = get(f"/data/wow/playable-race/{r['id']}") or {}
        races.append(clean({"id": r["id"], "name": nm(r), "kind": "Race", "faction": nm(d.get("faction")),
                            "classes": [nm(c) for c in d.get("playable_classes", [])],
                            "racials": [f"{nm(s)}: {spell(s['id'])}".rstrip(": ") for s in d.get("racial_spells", [])]}))
    cls = []
    for c in (get("/data/wow/playable-class/index") or {}).get("classes", []):
        d = get(f"/data/wow/playable-class/{c['id']}") or {}
        cls.append(clean({"id": c["id"], "name": nm(c), "kind": "Class", "power": nm(d.get("power_type")),
                          "specs": [nm(s) for s in d.get("specializations", [])],
                          "races": [nm(s) for s in d.get("playable_races", [])]}))
    save("classes", cls + races)


def talents():
    old = cached("talents")
    trees = (get("/data/wow/talent-tree/index") or {}).get("spec_talent_trees", [])
    order = {}
    for t in trees:  # tree layout gives each talent's row/column and max rank
        path = urllib.parse.urlparse((t.get("key") or {}).get("href", "")).path
        d = get(path) or {}
        for n in d.get("spec_talent_nodes", []):
            for r in n.get("ranks", [])[:1]:
                tid = ((r.get("tooltip") or {}).get("talent") or {}).get("id")
                if tid:
                    order[tid] = (n.get("display_row"), n.get("display_col"), len(n.get("ranks", [])))
    idx = (get("/data/wow/talent/index") or {}).get("talents", [])

    def one(m):
        if m["id"] in old:
            e = dict(old[m["id"]])
        else:
            d = get(f"/data/wow/talent/{m['id']}") or {}
            ranks = d.get("rank_descriptions") or []
            e = clean({"id": m["id"], "name": nm(m), "class": nm(d.get("playable_class")),
                       "spec": nm(d.get("playable_specialization")),
                       "how": (ranks[-1].get("description") if ranks else "") or "",
                       "ranks": len(ranks) or "", "spell": (d.get("spell") or {}).get("id")})
        row, col, mx = order.get(m["id"], (None, None, None))
        if row is not None:
            e["tier"] = row + 1 if isinstance(row, int) else row
        return e
    save("talents", pmap(one, idx))


# ---------------------------------------------------------------- quests
def quests():
    old = cached("quests")
    meta = {}
    areas = {a["id"]: nm(a) for a in (get("/data/wow/quest/area/index") or {}).get("areas", [])}
    for kind, idx_path, list_key, field in (("zone", "/data/wow/quest/area/index", "areas", "area"),
                                            ("category", "/data/wow/quest/category/index", "categories", "category"),
                                            ("type", "/data/wow/quest/type/index", "types", "type")):
        groups = (get(idx_path) or {}).get(list_key, [])

        def grp(g, kind=kind, idx_path=idx_path):
            return g, get(idx_path.replace("/index", f"/{g['id']}")) or {}
        for g, d in pmap(grp, groups):
            for q in d.get("quests", []):
                meta.setdefault(q["id"], {"id": q["id"], "name": nm(q)})[kind] = nm(g)
    todo = [q for q in meta if q not in old]
    print(f"quests listed: {len(meta)} ({len(todo)} need details)")
    sample = []

    def one(qid):
        d = get(f"/data/wow/quest/{qid}")
        if d and len(sample) < 2:
            sample.append(d)
        if not d:
            return qid, {}
        req, rw = d.get("requirements") or {}, d.get("rewards") or {}
        lv = req.get("min_character_level")
        mx = req.get("max_character_level")
        reps = [f"{nm(r.get('reward'))} +{r.get('value')}" for r in (rw.get("reputations") or []) if r.get("value")]
        items_ = []
        for grp_ in ("items", "choice_of"):
            v = (rw.get("items") or {}).get(grp_) if isinstance(rw.get("items"), dict) else None
            for it in (v or []):
                items_.append(nm(it.get("item") or it))
        fac = nm(req.get("faction"))
        return qid, clean({"how": d.get("description") or "", "level": d.get("recommended_minimum_level") or lv or "",
                           "reqLevel": lv or "", "maxLevel": mx or "", "faction": fac,
                           "xp": rw.get("experience") or "", "money": money((rw.get("money") or {}).get("value") or 0),
                           "reputation": reps, "rewardItems": items_,
                           "classes": [nm(c) for c in (req.get("classes") or [])],
                           "races": [nm(r) for r in (req.get("races") or [])]})
    for qid, extra in pmap(one, todo):
        old[qid] = {**meta[qid], **extra}
    for s in sample[:1]:
        print("quest sample:", json.dumps({k: v for k, v in s.items() if k != "_links"}, ensure_ascii=False)[:1500])
    out = []
    for qid, m in meta.items():
        e = {**old.get(qid, {}), **m}
        out.append(clean(e))
    save("quests", out, areas=areas)


# ---------------------------------------------------------------- professions & recipes
def professions():
    old = cached("recipes")
    profs, recipes, sample = [], [], []
    for p in (get("/data/wow/profession/index") or {}).get("professions", []):
        d = get(f"/data/wow/profession/{p['id']}") or {}
        tiers = []
        for t in d.get("skill_tiers", []):
            td = get(f"/data/wow/profession/{p['id']}/skill-tier/{t['id']}") or {}
            tiers.append(f"{nm(t)} ({td.get('minimum_skill_level', '?')}-{td.get('maximum_skill_level', '?')})")
            for cat in td.get("categories", []):
                for r in cat.get("recipes", []):
                    recipes.append({"id": r["id"], "name": nm(r), "profession": nm(p), "category": nm(cat)})
        profs.append(clean({"id": p["id"], "name": nm(p), "kind": nm(d.get("type")), "changes": d.get("description") or "",
                            "tiers": tiers}))
    save("professions", profs)

    def one(r):
        if r["id"] in old:
            return {**old[r["id"]], **r}
        d = get(f"/data/wow/recipe/{r['id']}") or {}
        if d and len(sample) < 1:
            sample.append(d)
        made = d.get("crafted_item") or d.get("alliance_crafted_item") or {}
        qty = (d.get("crafted_quantity") or {})
        q = qty.get("value") or qty.get("minimum")
        return clean({**r, "makes": (f"{q}x " if q and q > 1 else "") + nm(made) if made else (d.get("description") or ""),
                      "madeId": made.get("id"), "rank": d.get("rank") or "",
                      "reagents": [f"{x.get('quantity')}x {nm(x.get('reagent'))}" for x in d.get("reagents", [])]})
    out = pmap(one, recipes)
    for s in sample:
        print("recipe sample:", json.dumps({k: v for k, v in s.items() if k != "_links"}, ensure_ascii=False)[:1200])
    save("recipes", out)


ONLY = {s.strip() for s in os.environ.get("SECTIONS", "").split(",") if s.strip()}
for fn in (hunterpets, mounts, pets, toys, titles, itemsets, achievements, reputations, classes, talents, quests,
           professions, items):
    if not ONLY or fn.__name__ in ONLY:
        section(fn)
print(f"done: {_calls[0]} API calls, full refresh={FULL}")

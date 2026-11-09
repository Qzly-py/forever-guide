"""Enrich the Blizzard data (items.json, live/*.json) with facts from Questie's WoW: Forever database
(https://github.com/Questie/QuestieDB, GPLv3 per the Questie team; credited on the site): creature levels and
zones, quest givers, objectives and chains, and where items drop or are sold. Standard library only.
Run after scripts/update_blizzard.py."""
import re, json, pathlib, datetime, urllib.request
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = ROOT / "live"
RAW = "https://raw.githubusercontent.com/Questie/QuestieDB/master/"
UA = {"User-Agent": "ForeverFieldGuide/1.0 (fan guide; GitHub Actions)"}


def fetch(path):
    with urllib.request.urlopen(urllib.request.Request(RAW + path, headers=UA), timeout=120) as r:
        return r.read().decode("utf-8")


# ------------------------------------------------------------------ tiny Lua table-literal reader
class Lua:
    def __init__(self, s):
        self.s, self.i, self.n = s, 0, len(s)

    def ws(self):
        s, i, n = self.s, self.i, self.n
        while i < n:
            c = s[i]
            if c in " \t\r\n,;":
                i += 1
            elif s.startswith("--", i):
                if s.startswith("--[[", i):
                    j = s.find("]]", i)
                    i = n if j < 0 else j + 2
                else:
                    j = s.find("\n", i)
                    i = n if j < 0 else j + 1
            else:
                break
        self.i = i

    def value(self):
        self.ws()
        s, i = self.s, self.i
        c = s[i]
        if c == "{":
            return self.table()
        if c in "'\"":
            return self.string(c)
        if s.startswith("[[", i):
            j = s.find("]]", i)
            self.i = j + 2
            return s[i + 2:j]
        m = re.compile(r"-?(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)").match(s, i)
        if m:
            self.i = m.end()
            t = m.group(0)
            return int(t, 16) if "0x" in t.lower() else (float(t) if any(x in t for x in ".eE") else int(t))
        m = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*").match(s, i)
        if m:
            self.i = m.end()
            return {"nil": None, "true": True, "false": False}.get(m.group(0), m.group(0))
        raise ValueError(f"unexpected {s[i:i + 30]!r}")

    def string(self, q):
        s, i = self.s, self.i + 1
        out = []
        while True:
            c = s[i]
            if c == "\\":
                nx = s[i + 1]
                out.append({"n": "\n", "t": "\t"}.get(nx, nx))
                i += 2
            elif c == q:
                self.i = i + 1
                return "".join(out)
            else:
                j = i
                while s[j] not in (q, "\\"):
                    j += 1
                out.append(s[i:j])
                i = j

    def table(self):
        self.i += 1
        arr, d, keyed = [], {}, False
        while True:
            self.ws()
            s, i = self.s, self.i
            if s[i] == "}":
                self.i += 1
                break
            if s[i] == "[" and not s.startswith("[[", i):
                self.i += 1
                k = self.value()
                self.ws()
                self.i += 1  # ]
                self.ws()
                self.i += 1  # =
                d[k] = self.value()
                keyed = True
                continue
            m = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)").match(s, i)
            if m:
                self.i = m.end()
                d[m.group(1)] = self.value()
                keyed = True
                continue
            arr.append(self.value())
        if not keyed:
            return arr
        for n_, v in enumerate(arr, 1):
            d[n_] = v
        return d


def lua_db(text):
    m = re.search(r"\[\[return\s*", text) or re.search(r"=\s*\[=*\[\s*return\s*", text)
    return Lua(text[m.end():]).value()


def at(row, n):
    """1-based field from a Questie row (list with possible trailing gaps)."""
    if isinstance(row, dict):
        return row.get(n)
    return row[n - 1] if row and len(row) >= n else None


# ------------------------------------------------------------------ load
print("downloading Questie Forever data…")
NPC = lua_db(fetch("data/Forever/foreverNpcDB.lua"))
QUEST = lua_db(fetch("data/Forever/foreverQuestDB.lua"))
ITEM = lua_db(fetch("data/Forever/foreverItemDB.lua"))
OBJ = lua_db(fetch("data/Forever/foreverObjectDB.lua"))
print(f"npcs {len(NPC)}, quests {len(QUEST)}, items {len(ITEM)}, objects {len(OBJ)}")

# Zone names: Blizzard's quest areas first, then Questie's zone symbols and dungeon list.
FIX = {"Un Goro Crater": "Un'Goro Crater", "Zul Farrak": "Zul'Farrak", "Zul Gurub": "Zul'Gurub",
       "Ahn Qiraj": "Ahn'Qiraj", "Ruins Of Ahn Qiraj": "Ruins of Ahn'Qiraj", "Onyxias Lair": "Onyxia's Lair",
       "Quel Thalas": "Quel'Thalas", "The Temple Of Atal Hakkar": "The Temple of Atal'Hakkar",
       "Ironforge": "Ironforge", "Thunder Bluff": "Thunder Bluff", "Shen Dralar": "Shen'dralar"}
ZONES = {}
try:
    for k, v in re.findall(r"^\s*([A-Z0-9_]+)\s*=\s*(\d+)", fetch("src/corrections/enum/zones.lua"), re.M):
        if "PROTOTYPE" in k or "_OLD" in k:
            continue
        name = " ".join(w.capitalize() if w not in ("OF", "THE", "AND") or i == 0 else w.lower()
                        for i, w in enumerate(k.split("_")))
        ZONES.setdefault(int(v), FIX.get(name, name))
    for i, name in re.findall(r"\[(\d+)\]\s*=\s*\{\"([^\"]+)\"", fetch("support/Forever/Zones/dungeons.lua")):
        ZONES[int(i)] = name
except Exception as e:
    print("zone names:", e)
try:
    ZONES.update({int(k): v for k, v in json.loads((LIVE / "quests.json").read_text()).get("areas", {}).items()})
except Exception:
    pass
PARENT = {}
try:
    PARENT = {int(a): int(b) for a, b in re.findall(r"\[(\d+)\]\s*=\s*(\d+)", fetch("support/Forever/Zones/subZoneToParentZone.lua"))}
except Exception as e:
    print("sub-zones:", e)


def zone(zid):
    if not isinstance(zid, int) or zid <= 0:
        return ""
    return ZONES.get(PARENT.get(zid, zid)) or ZONES.get(zid) or ""


RANK = {1: "Elite", 2: "Rare elite", 3: "Boss", 4: "Rare"}


def npc_info(nid):
    r = NPC.get(nid)
    if not r:
        return None
    spawns = at(r, 7) or {}
    zs = [zone(z) for z, pts in sorted(spawns.items(), key=lambda kv: -len(kv[1] or [])) if zone(z)] if isinstance(spawns, dict) else []
    if not zs and zone(at(r, 9)):
        zs = [zone(at(r, 9))]
    lo, hi = at(r, 4), at(r, 5)
    lv = "" if not lo else (str(lo) if lo == hi or not hi else f"{lo}-{hi}")
    first = None
    if isinstance(spawns, dict):
        for z, pts in spawns.items():
            if pts and zone(z):
                first = (zone(z), pts[0])
                break
    return {"name": at(r, 1), "levels": lv, "zones": list(dict.fromkeys(zs)), "rank": RANK.get(at(r, 6), ""),
            "title": at(r, 14) or "", "friendly": at(r, 13) or "", "at": first}


def where_npc(nid):
    i = npc_info(nid)
    if not i:
        return ""
    loc = f" ({i['zones'][0]}" + (f" {i['at'][1][0]:.0f}, {i['at'][1][1]:.0f}" if i["at"] else "") + ")" if i["zones"] else ""
    return f"{i['name']}{loc}"


def where_obj(oid):
    r = OBJ.get(oid)
    if not r:
        return ""
    sp = at(r, 4) or {}
    z = next((zone(k) for k in sp if zone(k)), "") if isinstance(sp, dict) else ""
    return f"{at(r, 1)}" + (f" ({z})" if z else "")


def qname(qid):
    r = QUEST.get(qid)
    return at(r, 1) if r else ""


def load(p):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def write(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))


# ------------------------------------------------------------------ hunter pets: levels, zones, rarity
hp = load(LIVE / "hunterpets.json")
if hp:
    n = 0
    for e in hp["entries"]:
        i = npc_info(e.get("id"))
        if not i:
            continue
        n += 1
        e["levels"] = i["levels"] or e.get("levels", "")
        e["where"] = ", ".join(i["zones"][:6])
        e["zone"] = i["zones"][0] if i["zones"] else ""
        if i["rank"]:
            e["rank"] = i["rank"]
    write(LIVE / "hunterpets.json", hp)
    print(f"hunter pets enriched: {n}/{len(hp['entries'])}")

# ------------------------------------------------------------------ quests: givers, objectives, chains, zones
RACE = {1: "Human", 2: "Orc", 4: "Dwarf", 8: "Night Elf", 16: "Undead", 32: "Tauren", 64: "Gnome", 128: "Troll"}
CLS = {1: "Warrior", 2: "Paladin", 4: "Hunter", 8: "Rogue", 16: "Priest", 64: "Shaman", 128: "Mage", 256: "Warlock", 1024: "Druid"}
ALLY, HORDE = 1 | 4 | 8 | 64, 2 | 16 | 32 | 128


def quest_extra(qid):
    r = QUEST.get(qid)
    if not r:
        return None
    st, fin = at(r, 2) or [], at(r, 3) or []
    starts = [where_npc(x) for x in (at(st, 1) or [])] + [where_obj(x) for x in (at(st, 2) or [])] + \
             [f"{at(ITEM.get(x), 1)} (item)" for x in (at(st, 3) or []) if ITEM.get(x)]
    ends = [where_npc(x) for x in (at(fin, 1) or [])] + [where_obj(x) for x in (at(fin, 2) or [])]
    obj = at(r, 10) or []
    goals = []
    for kind in (1, 2, 3):
        for o in (at(obj, kind) or []):
            oid, txt = at(o, 1), at(o, 2)
            if txt:
                goals.append(txt)
            elif kind == 1 and npc_info(oid):
                goals.append(f"Kill {npc_info(oid)['name']}")
            elif kind == 2 and OBJ.get(oid):
                goals.append(f"Use {at(OBJ[oid], 1)}")
            elif kind == 3 and ITEM.get(oid):
                src = [npc_info(n)["name"] for n in (at(ITEM[oid], 2) or [])[:3] if npc_info(n)]
                goals.append(f"Collect {at(ITEM[oid], 1)}" + (f" (from {', '.join(src)})" if src else ""))
    rep = at(obj, 4)
    trig = at(r, 9)
    if trig and at(trig, 1):
        goals.append(at(trig, 1))
    races = at(r, 6) or 0
    fac = "Alliance" if races and not races & HORDE else "Horde" if races and not races & ALLY else ""
    pre = [qname(x) for x in (at(r, 12) or []) + (at(r, 13) or []) if qname(x)]
    nxt = qname(at(r, 22)) if at(r, 22) else ""
    zid = at(r, 17)
    zn = zone(zid) if isinstance(zid, int) and zid > 0 else ""
    if not zn and starts:
        i = npc_info((at(st, 1) or [None])[0])
        zn = i["zones"][0] if i and i["zones"] else ""
    lvl = at(r, 5)
    return {k: v for k, v in {
        "startsAt": "; ".join(x for x in starts if x), "endsAt": "; ".join(x for x in ends if x),
        "steps": goals, "objectivesText": " ".join(at(r, 8) or []) if isinstance(at(r, 8), list) else "",
        "level": lvl if isinstance(lvl, int) and lvl > 0 else None, "reqLevel": at(r, 4) or None,
        "faction": fac, "classes": [v for k, v in CLS.items() if (at(r, 7) or 0) & k] if at(r, 7) else [],
        "races": [v for k, v in RACE.items() if races & k] if races and races not in (ALLY, HORDE, 255) else [],
        "after": pre, "leadsTo": nxt, "zoneQ": zn,
        "repeatable": "Repeatable" if (at(r, 24) or 0) & 1 else "",
    }.items() if v not in (None, "", [], 0)}


qs = load(LIVE / "quests.json")
if qs is not None:
    have = {e["id"]: e for e in qs["entries"]}
    n = 0
    for qid in QUEST:
        x = quest_extra(qid)
        if not x:
            continue
        e = have.get(qid)
        if e is None:  # quests Questie knows but Blizzard didn't list
            e = have[qid] = {"id": qid, "name": qname(qid), "source": "Questie"}
            qs["entries"].append(e)
        n += 1
        for k, v in x.items():
            if k == "zoneQ":
                e.setdefault("zone", v)
            elif k in ("level", "reqLevel", "faction") and e.get(k):
                continue
            else:
                e[k] = v
        if not e.get("how") and x.get("objectivesText"):
            e["how"] = x["objectivesText"]
        e.pop("objectivesText", None)
    write(LIVE / "quests.json", qs)
    print(f"quests enriched: {n}, total {len(qs['entries'])}")

# ------------------------------------------------------------------ items: drops, vendors, quest rewards
it = load(ROOT / "items.json")
if it:
    n = 0
    for e in it["items"]:
        r = ITEM.get(e.get("id"))
        if not r:
            continue
        parts = []
        drops = [x for x in (at(r, 2) or []) if npc_info(x)]
        if drops:
            names = [where_npc(x) for x in drops[:6]]
            parts.append("Drops from " + ", ".join(names) + (f" and {len(drops) - 6} more" if len(drops) > 6 else ""))
        if at(r, 3):
            parts.append("Found in " + ", ".join(list(dict.fromkeys(where_obj(x) for x in at(r, 3)[:12] if where_obj(x)))[:4]))
        if at(r, 14):
            parts.append("Sold by " + ", ".join(list(dict.fromkeys(where_npc(x) for x in at(r, 14)[:12] if where_npc(x)))[:5]))
        if at(r, 6):
            parts.append("Reward from " + ", ".join(f"“{qname(q)}”" for q in at(r, 6)[:5] if qname(q)))
        if at(r, 4):
            parts.append("Contained in " + ", ".join(at(ITEM[x], 1) for x in at(r, 4)[:4] if ITEM.get(x)))
        if at(r, 5) and qname(at(r, 5)):
            parts.append(f"Starts the quest “{qname(at(r, 5))}”")
        if parts:
            e["where"] = ". ".join(p for p in parts if not p.endswith(("by ", "in ", "from "))) + "."
            e["source"] = "Drop" if drops or at(r, 3) else "Vendor" if at(r, 14) else "Quest" if at(r, 6) else "Other"
            n += 1
    # Forever-only items Questie doesn't know: use Blizzard's own quest rewards and recipes.
    rewards, crafted = {}, {}
    for q in (qs or {}).get("entries", []):
        for nm_ in q.get("rewardItems") or []:
            rewards.setdefault(nm_, []).append(q.get("name"))
    rec = load(LIVE / "recipes.json") or {}
    for r in rec.get("entries", []):
        if r.get("madeId"):
            crafted.setdefault(r["madeId"], []).append(f"{r.get('profession')} ({r.get('name')})")
    m = 0
    for e in it["items"]:
        parts = []
        if e.get("id") in crafted:
            parts.append("Crafted with " + ", ".join(dict.fromkeys(crafted[e["id"]])))
        if e.get("name") in rewards:
            parts.append("Reward from " + ", ".join(f"“{x}”" for x in list(dict.fromkeys(rewards[e["name"]]))[:5]))
        if not parts:
            continue
        extra = ". ".join(parts) + "."
        if not e.get("where"):
            e["where"] = extra
            e["source"] = "Crafted" if e.get("id") in crafted else "Quest"
            m += 1
        elif extra not in e["where"]:
            e["where"] += " " + extra
    write(ROOT / "items.json", it)
    print(f"items enriched: {n}/{len(it['items'])} from Questie, +{m} from Blizzard quests and recipes")

# ------------------------------------------------------------------ rares & elites list (named rare spawns)
rares = []
LOOT = {}  # npc -> items only a few creatures drop (i.e. that creature's own loot, not world drops)
for iid, ir in ITEM.items():
    d = at(ir, 2) or []
    if 0 < len(d) <= 3:
        for nid in d:
            LOOT.setdefault(nid, []).append(at(ir, 1))
for nid, r in NPC.items():
    if at(r, 6) not in (2, 4):
        continue
    i = npc_info(nid)
    if not i or not i["zones"]:
        continue
    loot = LOOT.get(nid, [])[:8]
    rares.append({"id": nid, "name": i["name"], "kind": i["rank"], "levels": i["levels"],
                  "where": ", ".join(i["zones"][:3]), "drops": loot})
write(LIVE / "rares.json", {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                            "entries": rares})
print(f"rares: {len(rares)}")

# ------------------------------------------------------------------ dungeon & raid loot, boss by boss
BYNAME = {}
for nid, r in NPC.items():
    nm_ = (at(r, 1) or "").lower()
    if nm_:
        BYNAME.setdefault(nm_, []).append(nid)
inst_out = []
for p in sorted((ROOT / "data").glob("instances*.json")):
    try:
        raw = json.loads(p.read_text())
    except Exception:
        continue
    if isinstance(raw, dict):
        raw = next((v for v in raw.values() if isinstance(v, list)), [])
    for ins in raw:
        if not isinstance(ins, dict) or not ins.get("name"):
            continue
        lines = []
        for b in ins.get("bosses") or []:
            bname = re.sub(r"\s*\(.*?\)\s*$", "", str(b)).strip()
            loot = []
            for nid in BYNAME.get(bname.lower(), []):
                loot += LOOT.get(nid, [])
            loot = list(dict.fromkeys(loot))[:12]
            if loot:
                lines.append(f"{bname}: {', '.join(loot)}")
        if lines:
            inst_out.append({"name": ins["name"], "bossLoot": lines})
write(LIVE / "instances.json", {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                "entries": inst_out})
print(f"instances with boss loot: {len(inst_out)}")

# ------------------------------------------------------------------ trainers, vendors & flight masters by zone (travel & services)
FLAGS = {8: "Flight master", 16: "Trainer", 128: "Vendor", 4096: "Repair", 65536: "Innkeeper", 1024: "Banker",
         2048: "Petitioner", 8192: "Stable master", 32768: "Auctioneer", 131072: "Battlemaster"}
svc = []
for nid, r in NPC.items():
    f = at(r, 15) or 0
    roles = [v for k, v in FLAGS.items() if f & k and v in ("Flight master", "Trainer", "Innkeeper", "Stable master",
                                                              "Auctioneer", "Banker", "Battlemaster")]
    if not roles:
        continue
    i = npc_info(nid)
    if not i or not i["zones"] or not i["at"]:
        continue
    x, y = i["at"][1]
    svc.append({"id": nid, "name": i["name"], "title": i["title"], "kind": roles[0], "zone": i["at"][0],
                "where": f"{i['at'][0]} ({x:.0f}, {y:.0f})",
                "faction": {"A": "Alliance", "H": "Horde", "AH": "Both"}.get(i["friendly"], "")})
# ------------------------------------------------------------------ vendors and what each one sells
SELLS = {}
for iid, ir in ITEM.items():
    for nid in (at(ir, 14) or []):
        SELLS.setdefault(nid, []).append(at(ir, 1))
BYID = {s["id"]: s for s in svc}
for nid, goods in SELLS.items():
    if nid in BYID:  # a trainer, innkeeper etc. who also sells things
        BYID[nid]["sells"] = sorted(set(g for g in goods if g))[:80]
        continue
    i = npc_info(nid)
    if not i or not i["zones"] or not i["at"]:
        continue
    x, y = i["at"][1]
    svc.append({"id": nid, "name": i["name"], "title": i["title"] or "Vendor", "kind": "Vendor", "zone": i["at"][0],
                "where": f"{i['at'][0]} ({x:.0f}, {y:.0f})", "sells": sorted(set(g for g in goods if g))[:80],
                "faction": {"A": "Alliance", "H": "Horde", "AH": "Both"}.get(i["friendly"], "")})
print(f"vendors with stock lists: {len(SELLS)}")

# ------------------------------------------------------------------ treasure chests and other lootable objects
CONTAINS = {}
for iid, ir in ITEM.items():
    for oid in (at(ir, 3) or []):
        CONTAINS.setdefault(oid, []).append(at(ir, 1))
CHEST = re.compile(r"chest|box|footlocker|strongbox|coffer|cache|crate|treasure|lockbox|trunk|stash|satchel|barrel|sack", re.I)
treasures = []
for oid, r in OBJ.items():
    name = at(r, 1) or ""
    sp = at(r, 4) or {}
    if not isinstance(sp, dict) or not sp or not (CHEST.search(name) or oid in CONTAINS):
        continue
    if at(r, 2) or at(r, 3):  # quest givers / turn-ins aren't treasure
        continue
    zones_ = Counter()
    sample = []
    for z, pts in sp.items():
        zn = zone(z)
        if zn and pts:
            zones_[zn] += len(pts)
            sample += [f"{zn} ({p[0]:.0f}, {p[1]:.0f})" for p in pts[:3]]
    if not zones_:
        continue
    loot = sorted(set(x for x in CONTAINS.get(oid, []) if x))
    treasures.append({"id": oid, "name": name, "kind": "Chest" if CHEST.search(name) else "Object",
                      "zone": zones_.most_common(1)[0][0],
                      "where": ", ".join(f"{z} ({n} spot{'s' if n > 1 else ''})" for z, n in zones_.most_common(8)),
                      "spots": sample[:12], "drops": loot[:40]})
write(LIVE / "treasures.json", {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                                "entries": treasures})
print(f"treasures/objects: {len(treasures)}")

write(LIVE / "services.json", {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                               "entries": svc})
print(f"services: {len(svc)}")

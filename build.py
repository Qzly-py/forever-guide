"""Merge data/<section>.json and data/<section>__*.json into data.json for the Forever Field Guide.
Entries with the same name are merged: empty fields are filled, lists are unioned.
Usage: python3 build.py"""
import json, sys, pathlib, datetime

root = pathlib.Path(__file__).parent
LISTS = ["mounts", "pets", "hunterpets", "gear", "quests", "zones", "instances", "classes", "professions", "news",
         "collectibles", "legacy", "reputations", "rares", "pvp", "events", "recipes", "travel"]


def empty(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v)


def key(name, it):
    if name == "news":
        return (it.get("url") or "") + "|" + (it.get("title") or "")
    if name == "hunterpets":
        return ((it.get("name") or "") + "|" + (it.get("family") or "")).lower()
    if name == "quests":
        return ((it.get("name") or "") + "|" + (it.get("faction") or "") + "|" + (it.get("zone") or "")).lower()
    return (it.get("name") or it.get("title") or "").strip().lower()


def merge(dst, src):
    for k, v in src.items():
        if empty(v):
            continue
        if empty(dst.get(k)):
            dst[k] = v
        elif isinstance(dst[k], list) and isinstance(v, list):
            for x in v:
                if x not in dst[k]:
                    dst[k].append(x)
        elif k == "confidence" and v == "confirmed":
            dst[k] = v


def load(p):
    val = json.loads(p.read_text())
    if isinstance(val, dict):
        val = next((v for v in val.values() if isinstance(v, list)), [])
    return [it for it in val if isinstance(it, dict)]


out = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
bad = False
for name in LISTS:
    files = sorted((root / "data").glob(f"{name}.json")) + sorted((root / "data").glob(f"{name}__*.json"))
    merged, index = [], {}
    for p in files:
        try:
            items = load(p)
        except Exception as e:
            print(f"{p.name}: INVALID JSON - {e}")
            bad = True
            continue
        for it in items:
            k = key(name, it)
            if k.strip("|") and k in index:
                merge(index[k], it)
            else:
                index[k] = it
                merged.append(it)
    for it in merged:
        if it.get("confidence") in ("forever-confirmed", "Forever-confirmed"):
            it["confidence"] = "confirmed"
    if name == "classes":
        for it in merged:
            n = it.get("name") or ""
            if n.startswith("_facts:"):
                it["name"] = n.split(":", 1)[1].strip().capitalize()
    if name == "pvp":
        for it in merged:
            n = (it.get("name") or "").lower()
            if it.get("kind") == "Rank" and not any(w in n for w in ("private", "grand marshal", "high warlord", "scout", "cap")):
                it["confidence"] = "vanilla-carryover"
    out[name] = merged
    print(f"{name}: {len(merged)}  ({', '.join(p.name for p in files) or 'no files'})")

sp = root / "data" / "systems.json"
out["systems"] = json.loads(sp.read_text()) if sp.exists() else {}
(root / "data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
print("wrote data.json", (root / "data.json").stat().st_size, "bytes")
sys.exit(1 if bad else 0)

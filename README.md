# Forever Field Guide

A searchable fan guidebook for World of Warcraft: Forever, covering mounts, pets, hunter pets, gear, quests, recipes, zones, dungeons and raids, reputations, rares, PvP, Legacy, events, travel and news.

Not affiliated with Blizzard Entertainment.

## How it stays up to date

- **Every hour**, the "Update guide" workflow (`.github/workflows/update.yml`) pulls new Forever stories from the Blizzard, Wowhead and Warcraft Tavern news feeds into `feed.json`.
- **Once a day (around 05:00 UTC)**, it downloads every item, plus any mounts and pets Blizzard lists, from the official Blizzard Game Data API into `items.json`. This needs two repository secrets: `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`, from develop.battle.net.
- **The written guides** (`data/*.json`, merged into `data.json` by `build.py`) are researched from community sources, and each entry links to its source.

You can also run an update by hand: **Actions → Update guide → Run workflow**.

## Files

- `index.html`: the whole site
- `data.json`: the researched guide content, built with `python3 build.py`
- `feed.json`, `items.json`: written automatically by the workflow
- `scripts/`: the updaters

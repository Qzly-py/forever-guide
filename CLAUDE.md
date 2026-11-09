# Forever Field Guide: setup for Claude Code

This folder is a finished, self-updating fan guide for World of Warcraft: Forever. The owner wants it published as a free GitHub Pages site that updates itself. Read README.md for how the site works.

## Your job: publish it and switch on the updater

Work through these steps in order. Tell the owner what you're doing in plain words; they are not a developer.

1. **Check the tools.** Make sure `git` and the GitHub CLI `gh` are installed (`git --version`, `gh --version`). If `gh` is missing, install it with `winget install --id GitHub.cli` (ask the owner first), then reopen the terminal.

2. **Sign in to GitHub.** Run `gh auth status`. If not signed in, run `gh auth login --web` and let the owner finish it in their browser. Never type passwords or tokens yourself.

3. **Create the repository and push.**
   ```
   git init -b main
   git add .
   git commit -m "Forever Field Guide"
   gh repo create forever-guide --public --source . --push
   ```
   If the name is taken on their account, ask the owner for another name.

4. **Turn on GitHub Pages using Actions:**
   ```
   gh api -X POST repos/{owner}/forever-guide/pages -f build_type=workflow
   ```
   (`{owner}` is the signed-in username from `gh api user -q .login`.) If Pages is already enabled, use `-X PUT` instead.

5. **Run the updater once:** `gh workflow run "Update guide"`, then watch it with `gh run watch`. When it succeeds, the site is at `https://<owner>.github.io/forever-guide/`. Give the owner that link.

6. **Blizzard key (adds every Forever item automatically).**
   - Open https://develop.battle.net/access/clients for the owner. They sign in, click **Create client**, give it any name, use `https://localhost` as the redirect URL, and accept Blizzard's API terms themselves.
   - Then run `gh secret set BLIZZARD_CLIENT_ID` and `gh secret set BLIZZARD_CLIENT_SECRET`. Each one prompts in the terminal, and the **owner pastes the value themselves**. Never ask them to paste the key into chat, and never echo it.
   - Run `gh workflow run "Update guide"` again and check the log shows items being downloaded.

7. **Done.** From then on the site updates itself: news every hour, Blizzard's item data daily, no Claude needed.

## Updating the written guides later

The researched content lives in `data/*.json`. To add or fix entries, edit those files (same field names as the existing entries), run `python build.py` to rebuild `data.json`, then commit and push. The site redeploys automatically on push.

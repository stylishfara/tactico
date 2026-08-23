---
name: squad-check
description: Check Tactico's squad data against current Wikipedia first-team squads and apply transfers. Use when asked to "check for new players", "check for transfers", "update the squads", "is the squad data current", "any new signings", or when a club's lineup looks out of date.
---

# Squad check

Tactico's squad data lives in one place: the `TEAMS` object in `index.html`.
This skill diffs it against Wikipedia and applies whatever has changed.

## 1. Run the diff

```bash
python3 tools/squad-diff.py                 # all 20 clubs (~50s)
python3 tools/squad-diff.py --club Arsenal  # one club (~3s)
python3 tools/squad-diff.py --cache         # reuse the last download
python3 tools/squad-diff.py --json          # machine-readable
```

It reports only and never edits `index.html`. Output categories:

| Marker | Meaning |
|---|---|
| `+` | in Wikipedia, not in Tactico — a signing or promoted academy player |
| `-` | in Tactico, not in Wikipedia — sold, released, or out on loan |
| `~` | that shirt number changed hands |
| `#` | same player, new shirt number |
| `LEAGUE:` | a club in `index.html` is no longer in the league |

Report the diff to the user before changing anything. Do not auto-apply.

## 2. Apply changes

Only after the user confirms. Edit the `TEAMS` block in `index.html`.

**Positions are the part that needs care.** The diff gives only Wikipedia's
coarse `GK/DF/MF/FW`; Tactico needs `GK, CB, RB, LB, DM, CM, AM, LM, RM, LW,
RW, ST`. For each new player, in this order:

1. Read `| position =` from their Wikipedia infobox (the `wiki:` page name in
   the diff output is the page title):
   ```bash
   curl -s -A "tactico/1.0" \
     "https://en.wikipedia.org/wiki/Special:Export/PAGE_TITLE" \
     | grep -m1 -o '| *position *=[^|]*'
   ```
2. If that is generic ("Midfielder", "Winger", "Forward"), scan the article
   body for the most frequent specific phrase — "left winger", "centre-back",
   "defensive midfielder" and so on.
3. Cross-check the result against the diff's coarse class. A `DF` that
   resolves to `CM` is a bad parse — investigate rather than accept it.
4. If it is still unclear, say so and ask. Never quietly guess a position.

**Ordering matters.** Each club's `players` array is a depth chart, not a
list: `pickXI` prefers earlier entries, and `DEPTH_W` in `pickXI` is what
stops a fringe exact-position match from displacing a senior player. So:

- A first-choice signing goes near the top, inside its position group.
- Fringe and academy players go at the end.
- Getting this wrong silently changes starting XIs — check the XI after.

**Other invariants:**

- Keep at least 2 `GK` per club, or the keeper slot falls back badly.
- Display names are surnames, with an initial only when a surname is
  ambiguous within that club (`L. Martínez`, `B. Fernandes`).
- Shirt numbers must be unique within a club.
- Players out on loan and squad entries with no shirt number are excluded by
  design — that is why some clubs show fewer players than Wikipedia lists.

## 3. Promotion and relegation

If the `LEAGUE:` line fires, the season has turned over:

1. Update the `WIKI` map and `SEASON_PAGE` in `tools/squad-diff.py`.
2. In `index.html`, remove relegated clubs and add promoted ones — each needs
   a `kit` entry (`body`, `sleeve`, optional `stripeColor`/`stripeType`,
   `collar`) alongside its `players`.

## 4. Verify before reporting done

```bash
# JS still parses
python3 -c "
import re;s=open('index.html',encoding='utf-8').read()
print('\n'.join(re.findall(r'<script[^>]*>(.*?)</script>',s,re.S)))" > /tmp/t.js && node --check /tmp/t.js

# squad invariants
python3 tools/squad-diff.py --cache        # should now be clean
```

Then check in a browser that every team and formation still fields 11 with a
keeper in goal, and that no starting XI changed unintentionally.

## 5. Ship

This repo pushes straight to `main` — commit and `git push origin main`. The
site is GitHub Pages at https://stylishfara.github.io/tactico/ and takes a
couple of minutes to publish; confirm by fetching the deployed file rather
than assuming.

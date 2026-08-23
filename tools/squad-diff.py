#!/usr/bin/env python3
"""Diff Tactico's squad data against the current Wikipedia first-team squads.

Reports only — it never edits index.html. Run from the repo root:

    python3 tools/squad-diff.py                # all clubs
    python3 tools/squad-diff.py --club Arsenal # one club
    python3 tools/squad-diff.py --json         # machine-readable
    python3 tools/squad-diff.py --cache        # reuse the last download

Source of truth is each club's Wikipedia page, section "First-team squad"
(some clubs title it "Current squad"). Players out on loan and squad entries
with no shirt number are skipped, matching how index.html is built.
"""
import argparse, html, json, os, re, sys, time, unicodedata, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
CACHE = os.path.join(ROOT, '.squad-cache')
UA = 'tactico-squad-diff/1.0 (https://github.com/stylishfara/tactico)'

# Tactico club name -> Wikipedia page title.
# Update this when clubs are promoted or relegated.
WIKI = {
    'Arsenal':'Arsenal F.C.', 'Aston Villa':'Aston Villa F.C.',
    'Bournemouth':'AFC Bournemouth', 'Brentford':'Brentford F.C.',
    'Brighton':'Brighton & Hove Albion F.C.', 'Chelsea':'Chelsea F.C.',
    'Coventry City':'Coventry City F.C.', 'Crystal Palace':'Crystal Palace F.C.',
    'Everton':'Everton F.C.', 'Fulham':'Fulham F.C.', 'Hull City':'Hull City A.F.C.',
    'Ipswich Town':'Ipswich Town F.C.', 'Leeds United':'Leeds United F.C.',
    'Liverpool':'Liverpool F.C.', 'Man City':'Manchester City F.C.',
    'Man United':'Manchester United F.C.', 'Newcastle':'Newcastle United F.C.',
    'Nottm Forest':'Nottingham Forest F.C.', 'Sunderland':'Sunderland A.F.C.',
    'Spurs':'Tottenham Hotspur F.C.',
}
SEASON_PAGE = '2026–27 Premier League'   # en dash; --season-page to override

PLAYER_RE = re.compile(r"""\{n:(\d+),name:(?:'([^']*)'|"([^"]*)"),pos:'([A-Z]+)'\}""")
SQUAD_TPL = re.compile(
    r"\{\{(?:Fs\s*player|football squad player)\|no=(\d*)\|nat=\w+\|pos=(\w+)"
    r"\|name=\[\[([^\]|]+)(?:\|([^\]]+))?\]\](.*)", re.I)


def fetch(title, use_cache):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, re.sub(r'\W+', '_', title) + '.xml')
    if use_cache and os.path.exists(path) and os.path.getsize(path) > 500:
        return open(path, encoding='utf-8').read()
    url = 'https://en.wikipedia.org/wiki/Special:Export/' + urllib.parse.quote(
        title.replace(' ', '_'), safe='')
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        text = r.read().decode('utf-8', 'replace')
    open(path, 'w', encoding='utf-8').write(text)
    time.sleep(0.3)                      # be polite to Wikipedia
    return text


def current_squads():
    """Parse the TEAMS block out of index.html."""
    src = open(INDEX, encoding='utf-8').read()
    start = src.index('const TEAMS = {')
    end = src.index('\n};', start)
    block = src[start:end]
    out, club = {}, None
    for line in block.split('\n'):
        m = re.match(r"\s*'([^']+)':\{kit:", line)
        if m:
            club = m.group(1); out[club] = []
        if club:
            for n, n1, n2, pos in PLAYER_RE.findall(line):
                out[club].append({'n': int(n), 'name': n1 or n2, 'pos': pos})
    return out


def wiki_squad(title, use_cache):
    """Numbered, non-loaned players from the first-team squad section."""
    text = html.unescape(fetch(title, use_cache))
    lines, start, stop = text.split('\n'), None, None
    for i, ln in enumerate(lines):
        if start is None:
            if ln.startswith('=') and re.search(r'first[- ]team squad|current squad', ln, re.I):
                start = i
        elif ln.startswith('=') and ln.rstrip().endswith('='):
            stop = i; break
    if start is None:
        return None, 'no first-team squad section found'
    seg = '\n'.join(lines[start + 1:stop])
    players, seen, skipped = [], set(), 0
    for no, pos, page, alias, rest in SQUAD_TPL.findall(seg):
        if 'on loan to' in rest:
            continue
        if not no:
            skipped += 1; continue
        if int(no) in seen:
            continue
        seen.add(int(no))
        players.append({'n': int(no), 'name': (alias or page).strip(),
                        'page': page.strip(), 'coarse': pos.upper()})
    return sorted(players, key=lambda p: p['n']), (
        f'{skipped} squad entries had no shirt number' if skipped else None)


def norm(text):
    """Lowercase, strip diacritics and punctuation, for name comparison."""
    t = unicodedata.normalize('NFKD', text)
    t = ''.join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]", '', t).strip()


def compatible(a, b):
    """index.html carries short display names ('Kepa', 'B. Fernandes') while
    Wikipedia carries full ones. Treat them as the same player when either
    contains the other, or they share a name token of 3+ characters."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ta = {t for t in na.split() if len(t) >= 3}
    tb = {t for t in nb.split() if len(t) >= 3}
    return bool(ta & tb)


def diff_club(have, wiki):
    """Match by shirt number first, then by name, and report what is left."""
    rest_h, rest_w = list(have), list(wiki)
    renumbered, replaced = [], []

    # 1. same number, compatible name -> unchanged
    for h in list(rest_h):
        w = next((x for x in rest_w if x['n'] == h['n']), None)
        if w and compatible(h['name'], w['name']):
            rest_h.remove(h); rest_w.remove(w)

    # 2. compatible name at a different number -> renumbered
    for h in list(rest_h):
        w = next((x for x in rest_w if compatible(h['name'], x['name'])), None)
        if w:
            renumbered.append((h['name'], h['n'], w['n']))
            rest_h.remove(h); rest_w.remove(w)

    # 3. same number, different player -> the number changed hands
    for h in list(rest_h):
        w = next((x for x in rest_w if x['n'] == h['n']), None)
        if w:
            replaced.append((h['n'], h['name'], w['name'], w))
            rest_h.remove(h); rest_w.remove(w)

    return {'added': rest_w, 'removed': rest_h,
            'renumbered': renumbered, 'replaced': replaced}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--club'); ap.add_argument('--json', action='store_true')
    ap.add_argument('--cache', action='store_true')
    ap.add_argument('--season-page', default=SEASON_PAGE)
    a = ap.parse_args()

    have = current_squads()
    clubs = [a.club] if a.club else list(have)
    for c in clubs:
        if c not in have:
            sys.exit(f'"{c}" is not in index.html. Known: {", ".join(sorted(have))}')

    # League membership: catches promotion/relegation, which the club diff cannot.
    league_note = None
    if not a.club:
        try:
            season = html.unescape(fetch(a.season_page, a.cache))
            listed = set(re.findall(r'\{\{[Ss]ortname\|[^|]*\|([^}|]+)', season))
            names = {WIKI[c].replace(' F.C.', '').replace(' A.F.C.', '')
                     .replace('AFC ', '').strip() for c in have}
            missing = [n for n in names if n and not any(n in l for l in listed)] if listed else []
            if missing:
                league_note = ('clubs in index.html not found on ' + a.season_page +
                               ': ' + ', '.join(sorted(missing)))
        except Exception as e:
            league_note = f'could not check league membership ({e})'

    report, total = {}, 0
    for c in clubs:
        wiki, note = wiki_squad(WIKI[c], a.cache)
        if wiki is None:
            report[c] = {'error': note}; continue
        d = diff_club(have[c], wiki)
        d['note'] = note
        d['counts'] = {'index': len(have[c]), 'wikipedia': len(wiki)}
        total += len(d['added']) + len(d['removed']) + len(d['replaced']) + len(d['renumbered'])
        report[c] = d

    if a.json:
        print(json.dumps({'league_note': league_note, 'clubs': report}, indent=1, ensure_ascii=False))
        return

    if league_note:
        print('LEAGUE: ' + league_note + '\n')
    quiet = []
    for c, d in report.items():
        if 'error' in d:
            print(f'{c}: ERROR — {d["error"]}'); continue
        n = len(d['added']) + len(d['removed']) + len(d['replaced']) + len(d['renumbered'])
        if not n:
            quiet.append(c); continue
        print(f'{c}  (index {d["counts"]["index"]}, wikipedia {d["counts"]["wikipedia"]})')
        for p in d['added']:
            print(f'   + {p["n"]:>3} {p["name"]}  [{p["coarse"]}]  wiki: {p["page"]}')
        for p in d['removed']:
            print(f'   - {p["n"]:>3} {p["name"]}  [{p["pos"]}]')
        for n_, old, new, w in d['replaced']:
            print(f'   ~ {n_:>3} {old} -> {new}  [{w["coarse"]}]  wiki: {w["page"]}')
        for nm, o, w in d['renumbered']:
            print(f'   # {nm}: {o} -> {w}')
        if d['note']:
            print(f'     note: {d["note"]}')
        print()
    if quiet:
        print(f'unchanged ({len(quiet)}): ' + ', '.join(quiet))
    print(f'\n{total} differences across {len(clubs)} club(s).')


if __name__ == '__main__':
    main()

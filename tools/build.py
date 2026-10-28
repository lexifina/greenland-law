"""Builds a git repository of Greenlandic law from Nalunaarutit (nalunaarutit.gl), in which every amending act is one
commit, dated the day it took effect.

    python -X utf8 scripts/greenland-law/build.py [--repo ../greenland-law] [--today 2026-10-28] [--offline]
                                                  [--verify-rebuild]

Nalunaarutit, the official electronic law collection of Grønlands Selvstyre, publishes each act as passed (Inatsisartutlov,
landstingslov) and each consolidation (Selvstyrets lovbekendtgørelse) as a page of its own. A consolidation says in its
opening words which amending acts it incorporates, quotes each act's commencement clause after the text, and says in an
endnote per act which provisions that act changed ("Lovændringen vedrører § 3, stk. 1, nr. 3 og stk. 2"). We take the act
as passed and every later consolidation, compare consecutive versions provision by provision, and credit each changed
provision to the amending act whose endnote or amending article names it. The day a change took effect is read from the
amending act's own commencement sentence ("Inatsisartutloven træder i kraft den 1. januar 2019"). A change nothing
explains, a change of paragraph breaks alone, and a change a consolidation prints before its act takes effect are
never credited to an act: they are committed by Nalunaarutit, labelled.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import glfetch
import glparse as P
from glfetch import fetch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMMITTER = ('Lexifina', 'greenland-law@lexifina.com')
PUBLISHER = ('Nalunaarutit (Grønlands Selvstyre)', 'nalunaarutit@nalunaarutit.invalid')
SITE = 'https://nalunaarutit.gl'
LANG = '?sc_lang=da'

# The acts in the record: the page of the act as passed, its number and year, and a word of its title that the amending
# article of a multi-act amending law uses to name it.
ACTS = [
    {'slug': 'kirken', 'short': 'Kirkeloven', 'path': '/Groenlandsk-lovgivning/2010/ltl-09-2010', 'number': 9, 'year': 2010,
     'law': 'kirken'},
    {'slug': 'havneafgift', 'short': 'Havneafgiftsloven', 'path': '/Groenlandsk-lovgivning/1992/ltl-20-1992', 'number': 20,
     'year': 1992, 'law': 'havneafgift'},
]
EDITORIAL = ('indledning', 'ikraft', 'slut', 'noter')
PREFIX = {'inatsisartutlov': 'il', 'landstingslov': 'ltl', 'landstingsforordning': 'ltf', 'inatsisartutforordning': 'if',
          'lovbekendtgørelse': 'lbk'}


# ---------------------------------------------------------------- Nalunaarutit documents

def slug_day(path: str) -> str | None:
    m = re.search(r'-(\d{2})[_-](\d{2})[_-](\d{4})$', path)
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def kind_of(title: str) -> str:
    t = title.lower()
    if t.startswith('selvstyrets lovbekendtg'):
        return 'lovbekendtgørelse'
    for k in ('inatsisartutlov', 'landstingslov', 'landstingsforordning', 'inatsisartutforordning'):
        if t.startswith(k):
            return k
    return 'lov'


def document(path: str, offline: bool) -> dict:
    """A document by its page path: parsed page plus its record (label, kind, designation day, site day, status)."""
    raw = fetch(path + LANG, offline=offline)
    if not raw:
        raise SystemExit(f'no page at {path}')
    html = raw.decode('utf-8')
    pg = P.page(html)
    kind = kind_of(pg['title'])
    day = slug_day(path) or pg['site_day']
    label = ('Selvstyrets lovbekendtgørelse' if kind == 'lovbekendtgørelse' else kind.capitalize()) + \
        f' nr. {pg["number"]} af {P.long_day(day)}'
    signed = None
    return {'path': path, 'url': SITE + path + LANG, 'page': pg, 'title': pg['title'], 'kind': kind, 'number': pg['number'],
            'year': int(day[:4]), 'enacted': day, 'site_day': pg['site_day'], 'status': pg['status'], 'label': label,
            'sha256': hashlib.sha256(raw).hexdigest(), 'signed': signed}


def sitemap(offline: bool) -> list[str]:
    xml = fetch('/api/sitemap/sitemapxml', offline=offline).decode('utf-8')
    locs = re.findall(r'<loc>([^<]+)</loc>', xml)
    return sorted({l.replace(SITE, '').split('?')[0] for l in locs if '/Groenlandsk-lovgivning/' in l and l.endswith('sc_lang=da')})


def resolve(num: int, year: int, rels: list[tuple[str, str]], paths: list[str]) -> str | None:
    """The page of an act named by number and year: a sidebar link whose text ends '- (num/year)', else the sitemap page
    whose slug carries the number and year."""
    for href, text in rels:
        if text.endswith(f'({num}/{year})'):
            return href
    pats = [f'/{year}/ltl-{num:02d}-{year}', f'/{year}/ltf-{num:02d}-{year}', f'/{year}/L-{num:02d}-{year}',
            f'/{year}/ltl-{num}-{year}', f'/{year}/L-{num}-{year}']
    for p in paths:
        if any(p.endswith(x) for x in pats) or re.search(rf'/{year}/Inatsisartutlov-nr-{num}-af-\d\d_\d\d_{year}$', p):
            return p
    return None


# ---------------------------------------------------------------- one act: versions, changes, causes

def heads_split(t: str | None) -> tuple[list[str], set[str]]:
    lines = (t or '').rstrip('\n').split('\n\n') if t else []
    return [l for l in lines if not l.startswith('## ')], {l for l in lines if l.startswith('## ')}


NORM = re.compile(r'\W+')


def norm_words(t: str | None) -> str:
    return NORM.sub('', (t or '').lower())


def act_norm(doc: dict) -> str:
    return NORM.sub('', ' '.join(t for _, t in doc['page']['lines']).lower())


def added_lines(p: dict | None, c: dict) -> list[str]:
    old = set(NORM.sub('', l.lower()) for l in (p['lines'] if p else []))
    return [NORM.sub('', l.lower()) for l in c['lines'] if len(l) >= 40 and not l.startswith('## ')
            and NORM.sub('', l.lower()) not in old]


def base_ref(act: dict, docs: dict) -> re.Pattern:
    d = docs[act['path']]
    return re.compile(rf'nr\.?\s*{act["number"]}\.?\s+af\s+{re.escape(P.long_day(d["enacted"]))}', re.I)


def read_act(act: dict, offline: bool, paths: list[str]) -> dict:
    docs = {act['path']: document(act['path'], offline)}
    ref = base_ref(act, docs)
    lbks = []
    for p in paths:
        if 'lovbekendtg' not in p.lower():
            continue
        d = document(p, offline)
        pre = ' '.join(t for _, t in d['page']['lines'][:3])
        if ref.search(pre) and pre.startswith(('Herved bekendtg', 'Hermed bekendtg')):
            lbks.append(d)
    lbks.sort(key=lambda d: (d['enacted'], d['number']))
    versions = []
    for d in [docs[act['path']]] + lbks:
        docs[d['path']] = d
        parsed = P.read_units(d['page'])
        versions.append({'key': d['path'], 'kind': d['kind'], 'doc': d, 'from': d['enacted'] if d is not docs[act['path']] else None,
                         'units': parsed['units'], 'sha256': d['sha256'], 'url': d['url'], 'page': d['url'], 'laws': [],
                         'incorporated': P.preamble_acts(parsed['units'].get('indledning', {}).get('text', ''))})
    return {'act': act, 'versions': versions, 'docs': docs}


def analyse_act(doc: dict, act: dict, docs: dict) -> dict:
    """What an amending act amends and when: the article(s) that amend our law, the provisions each item names, the
    commencement day and sentence, and the sentences giving parts of it effect from another day."""
    lines = doc['page']['lines']
    arts = P.articles(lines)
    ref = base_ref(act, docs)
    nums = [n for n, t in sorted(arts.items()) if len(t) > 1 and ref.search(t[1])]
    if not nums:
        nums = [n for n, t in sorted(arts.items()) if len(t) > 1 and act['law'] in t[1].lower() and
                re.search(r'foretages følgende ændring', t[1])]
    items: dict[int, dict[int, set[str]]] = {n: P.items_of(arts[n]) for n in nums}
    named: dict[str, list[tuple[int, int]]] = {}
    for n, its in items.items():
        for i, secs in its.items():
            for s in secs:
                named.setdefault(s, []).append((n, i))
    day, sentence = P.commencement(arts, lines)
    return {'articles': nums, 'named': named, 'items': items, 'arts': arts, 'day': day, 'sentence': sentence,
            'applies': P.applies_sentences(arts)}


def build_act(act: dict, offline: bool, paths: list[str]) -> dict:
    r = read_act(act, offline, paths)
    versions, docs = r['versions'], r['docs']
    own = act['path']
    base = docs[own]
    day0, sentence0 = P.commencement({}, base['page']['lines'])
    if not day0:
        raise SystemExit(f'{own}: no commencement day read')
    versions[0]['from'] = day0
    versions[0]['own_sentence'] = sentence0
    changes, problems = [], []
    laws: dict[str, dict] = {own: base}
    analyses: dict[tuple, dict] = {}
    all_rels = [x for v in versions for x in v['doc']['page']['rels']]
    for prev, cur in zip(versions, versions[1:]):
        done = {(n, y) for v in versions[:versions.index(cur)] for _, n, y, _ in v['incorporated']}
        acts = []
        for kind, n, y, d in cur['incorporated']:
            if (n, y) in done or (n, y) == (act['number'], act['year']):
                continue
            p = resolve(n, y, all_rels, paths)
            if not p:
                raise SystemExit(f'{act["slug"]}: no page for act {n}/{y} named by {cur["key"]}')
            if p not in laws:
                laws[p] = document(p, offline)
            acts.append(p)
        cur['laws'] = acts
        window_prev, window_cur = prev['from'], cur['from']
        notes = P.note_map(cur['units'])
        ikraft = P.ikraft_map(cur['units'])
        for p in acts:
            an = analyse_act(laws[p], act, docs)
            analyses[(p, cur['key'])] = an
            # the consolidation's own statement of what this act changed (endnote) and its quoted commencement clause
            idx = next((i for i, (a, _) in ikraft.items() if a and (a[1], a[2]) == (laws[p]['number'], laws[p]['year'])), None)
            if idx is None:
                order = [(n, y) for _, n, y, _ in cur['incorporated']]
                idx = order.index((laws[p]['number'], laws[p]['year'])) + 1 if (laws[p]['number'], laws[p]['year']) in order else None
            an['note'] = sorted(notes.get(idx, set()), key=P.unit_order) if idx else []
            an['note_index'] = idx
            an['quoted'] = ikraft.get(idx, (None, []))[1] if idx else []
            qday = next((P.danish_day(l) for l in an['quoted'] if re.search(r'træder i kraft', l)), None)
            an['quoted_day'] = qday
            for u in an['note']:
                an['named'].setdefault(u, [])
            an['early'] = bool(an['day'] and an['day'] > window_cur)
        normal = [p for p in acts if not analyses[(p, cur['key'])]['early']]
        early = [p for p in acts if analyses[(p, cur['key'])]['early']]
        norms = {p: act_norm(laws[p]) for p in acts}
        allkeys = sorted(set(prev['units']) | set(cur['units']), key=P.unit_order)
        changed = [k for k in allkeys if (prev['units'].get(k) or {}).get('text') != (cur['units'].get(k) or {}).get('text')]
        cause, why, when, evid = {}, {}, {}, {}
        for u in changed:
            p_, c_ = prev['units'].get(u), cur['units'].get(u)
            if u in EDITORIAL:
                cause[u], why[u] = 'publisher', 'editorial part of the consolidation (opening words, commencement clauses, signatures, notes)'
                continue
            if p_ and c_ and norm_words(p_['text']) == norm_words(c_['text']):
                cause[u], why[u] = 'layout', 'only paragraph breaks or white space differ; no word changed'
                continue
            cands = [p for p in acts if u in analyses[(p, cur['key'])]['named']]
            if len(cands) == 1 and cands[0] in normal:
                cause[u], why[u] = cands[0], 'named by the consolidation’s endnote or the amending article'
            elif len(cands) == 1:
                cause[u], why[u] = 'early:' + cands[0], 'printed by the consolidation before the act takes effect'
            elif len(cands) > 1:
                cause[u], why[u] = 'candidates', 'named by the endnotes or amending articles of more than one act'
                evid[u] = cands
            else:
                gl = [p for p in acts if '*' in analyses[(p, cur['key'])]['named']]
                if len(gl) == 1 and gl[0] in normal:
                    cause[u], why[u] = gl[0], 'global replacement item of the amending article'
                elif len(gl) > 1:
                    cause[u], why[u] = 'candidates', 'global replacement items of more than one act'
                    evid[u] = gl
                else:
                    hits = []
                    add = added_lines(p_, c_) if c_ else []
                    if add:
                        for p in acts:
                            if any(x in norms[p] for x in add):
                                hits.append(p)
                    if len(hits) == 1 and hits[0] in normal:
                        cause[u], why[u] = hits[0], 'the new wording is quoted in the amending act'
                    elif len(hits) == 1:
                        cause[u], why[u] = 'early:' + hits[0], 'the new wording is quoted in an act the consolidation prints before it takes effect'
                    elif len(hits) > 1:
                        cause[u], why[u] = 'candidates', 'the new wording is quoted in more than one act'
                        evid[u] = hits
                    else:
                        cause[u], why[u] = 'unexplained', 'no endnote and no amending article of the consolidation names it'
        order = sorted(set(prev['units']) | set(cur['units']), key=P.unit_order)
        for u in changed:
            if cause[u] != 'unexplained':
                continue
            p_, c_ = prev['units'].get(u), cur['units'].get(u)
            if p_ and c_ and heads_split(p_['text'])[0] == heads_split(c_['text'])[0]:
                moved = heads_split(p_['text'])[1] ^ heads_split(c_['text'])[1]
                i = order.index(u)
                for nb in (order[i - 1] if i else None, order[i + 1] if i + 1 < len(order) else None):
                    if nb in cause and cause[nb] in laws and moved:
                        cause[u], why[u] = cause[nb], f'headings moved with {nb}'
                        break
        groups: dict[tuple, list[str]] = {}
        for u in changed:
            c = cause[u]
            if c in ('unexplained', 'publisher', 'layout') or c.startswith('early:'):
                when[u] = window_cur
                groups.setdefault((c, window_cur), []).append(u)
                continue
            if c == 'candidates':
                ds = [analyses[(p, cur['key'])]['day'] for p in evid[u]]
                d = max(x for x in ds if x) if any(ds) else window_cur
                d = min(d, window_cur)
                when[u] = d
                groups.setdefault(('candidates:' + ','.join(sorted(evid[u])), d), []).append(u)
                continue
            an = analyses[(c, cur['key'])]
            d, note = an['day'], ''
            if d is None:
                d, note = window_cur, 'undated'
            elif d < window_prev:
                d, note = window_prev, 'late'
            when[u] = d
            evid[u] = an['sentence']
            why[u] = why[u] + ('' if not note else f'; day {note}')
            groups.setdefault((c, d), []).append(u)
        for p in normal:   # every incorporated act is in the record, even if no file of ours changes that day
            if not any(g[0] == p for g in groups):
                an = analyses[(p, cur['key'])]
                d = an['day']
                d2 = d if d and window_prev <= d <= window_cur else window_cur
                groups[(p, d2)] = []
        for p in early:
            if not any(g[0] == 'early:' + p for g in groups):
                groups[('early:' + p, window_cur)] = []
        for u in changed:
            if cause[u] == 'unexplained':
                problems.append(f'{cur["from"]} {u} ({why[u]})')
        changes.append({'from': cur['from'], 'url': cur['page'], 'laws': acts, 'groups': groups, 'cause': cause, 'why': why,
                        'when': when, 'evid': evid, 'prev': prev, 'cur': cur,
                        'analyses': {p: analyses[(p, cur['key'])] for p in acts}, 'window': (window_prev, window_cur)})
    return {'act': act, 'versions': versions, 'laws': laws, 'changes': changes, 'problems': problems,
            'title': P.act_title(base['title']), 'label': base['label'], 'key': own}


# ---------------------------------------------------------------- the git repository

def git(repo: Path, *args: str, env: dict | None = None, input: str | None = None) -> str:
    out = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, encoding='utf-8', env=env, input=input)
    if out.returncode:
        raise SystemExit(f'git {" ".join(args)} failed: {out.stderr}')
    return out.stdout


def last_sunday(year: int, month: int) -> dt.date:
    d = (dt.date(year, month + 1, 1) if month < 12 else dt.date(year + 1, 1, 1)) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def eu_summer(day: dt.date) -> bool:
    """European summer time on a day (at noon): 1980 from 6 April to 28 September; 1981-1995 from the last Sunday in March
    to the last Sunday in September; from 1996 to the last Sunday in October."""
    y = day.year
    if y < 1980:
        return False
    if y == 1980:
        return dt.date(1980, 4, 6) <= day < dt.date(1980, 9, 28)
    return last_sunday(y, 3) <= day < last_sunday(y, 9 if y < 1996 else 10)


def nuuk_offset(day: dt.date) -> int:
    """Hours ahead of UTC at noon on a day in Nuuk (written out: this machine has no tz database). UTC-3 with European
    summer time (UTC-2) from 1980 to 25 March 2023; then UTC-2 all year until 30 March 2024 (no change back in October
    2023); since 31 March 2024 UTC-2 as standard time with European summer time (UTC-1)."""
    if day < dt.date(2023, 3, 26):
        return -2 if eu_summer(day) else -3
    if day < dt.date(2024, 3, 31):
        return -2
    return -1 if eu_summer(day) else -2


def commit_date(day: str, seq: list[int]) -> str:
    """Noon in Nuuk on the day. Git cannot record a time before 1970, so changes in force before then are dated
    1 January 1970 (UTC), one second apart in the order they took effect; the real day is in the In-force trailer."""
    d = dt.date.fromisoformat(day)
    if d.year < 1970:
        seq[0] += 1
        return f'@{seq[0]} +0000'
    off = nuuk_offset(d)
    stamp = int(dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone(dt.timedelta(hours=off))).timestamp())
    return f'@{stamp} -0{-off}00'


def author_of(doc: dict) -> tuple[str, str]:
    return doc['label'], f'{PREFIX[doc["kind"]]}-{doc["year"]}-{doc["number"]}@nalunaarutit.invalid'


def tag_of(doc: dict) -> str:
    return f'{PREFIX[doc["kind"]]}/{doc["year"]}-{doc["number"]}'


def write_unit(repo: Path, slug: str, key: str, unit: dict | None):
    path = repo / slug / f'{key}.md'
    if unit is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit['text'], encoding='utf-8', newline='\n')


PRE_1970 = ['Git kan ikke gemme datoer før 1970, så denne commit er dateret 1. januar 1970; ikrafttrædelsesdagen står',
            'i linjen In-force. (Git cannot record dates before 1970: the real day is In-force.)', '']


def plan_commits(built: list[dict]) -> list[tuple]:
    """Every commit, sorted by day: the first version of each act first on its day, then one commit per amending act (in
    order of designation), then changes credited to several candidate acts, then changes printed early, then the
    consolidation's own editorial commit (last on its day, so the repository on that day equals the official text)."""
    commits = []
    for ai, b in enumerate(built):
        commits.append((b['versions'][0]['from'], ai, 0, '', {'kind': 'start', 'b': b}))
        for ch in b['changes']:
            for (grp, day), keys in ch['groups'].items():
                if grp in ('unexplained', 'publisher', 'layout'):
                    continue
                if grp.startswith('candidates:'):
                    commits.append((day, ai, 2, grp, {'kind': 'candidates', 'b': b, 'ch': ch, 'grp': grp, 'day': day}))
                elif grp.startswith('early:'):
                    commits.append((day, ai, 3, grp, {'kind': 'early', 'b': b, 'ch': ch, 'grp': grp, 'law': grp[6:], 'day': day}))
                else:
                    lm = b['laws'][grp]
                    commits.append((day, ai, 1, f'{lm["enacted"]}-{lm["number"]:04d}', {'kind': 'law', 'b': b, 'ch': ch, 'law': grp, 'day': day}))
            commits.append((ch['from'], ai, 4, '', {'kind': 'consolidation', 'b': b, 'ch': ch, 'day': ch['from']}))
    commits.sort(key=lambda c: c[:4])
    return commits


def units_of(ch: dict, grp: str, day: str) -> list[str]:
    return sorted(ch['groups'].get((grp, day), []), key=P.unit_order)


def listing(ch: dict, keys: list[str]) -> tuple[list[str], list[str]]:
    labels, lines = [], []
    by: dict[str, list[str]] = {}
    for k in keys:
        p, c = ch['prev']['units'].get(k), ch['cur']['units'].get(k)
        lab = (c or p)['label']
        labels.append(lab)
        by.setdefault('Indsat' if p is None else 'Udgået' if c is None else 'Ændret', []).append(lab)
    for name in ('Indsat', 'Ændret', 'Udgået'):
        if name in by:
            lines.append(f'{name}: {", ".join(by[name])}')
    return labels, lines


def doc_trailers(d: dict) -> list[str]:
    t = [f'Kind: {d["kind"]}', f'Enacted: {d["enacted"]}']
    if d['site_day'] and d['site_day'] != d['enacted']:
        t.append(f'Site-date: {d["site_day"]}')
    if d['status']:
        t.append(f'Status: {d["status"]}')
    return t


def start_message(b: dict, day: str):
    v = b['versions'][0]
    d = b['laws'][b['key']]
    author = author_of(d)
    msg = [f'{b["act"]["short"]}: {b["title"]} ({d["label"]})', '',
           'Loven som vedtaget, i den tekst Nalunaarutit udgiver den i, med ikrafttræden fra denne dag.', '',
           'The act as passed, in the text Nalunaarutit publishes it in, in force from this day.', '']
    trailers = doc_trailers(d) + [f'In-force: {day}']
    if v.get('own_sentence'):
        msg += ['Ikrafttræden læst i loven selv:', '', f'> {v["own_sentence"]}', '',
                'Commencement read from the act itself, quoted above.', '']
        trailers.append('Evidence: commencement clause of the act itself')
    trailers += [f'Source: {d["url"]}']
    if day < '1970-01-01':
        msg += PRE_1970
    return author, msg, trailers


def change_message(b: dict, c: dict):
    ch, kind = c['ch'], c['kind']
    short = b['act']['short']
    day = c['day']
    trailers = []
    if kind == 'law':
        law = c['law']
        keys = units_of(ch, law, day)
        labels, lst = listing(ch, keys)
        lm = b['laws'][law]
        an = ch['analyses'][law]
        author = author_of(lm)
        subject = f'{short}: {", ".join(labels) if labels else "ingen ændring i teksten"} ({lm["label"]})'
        if len(subject) > 100:
            subject = f'{short}: {len(labels)} bestemmelser ({lm["label"]})'
        msg = [subject, '', lm['title'], ''] + lst + ([''] if lst else [])
        if not keys:
            msg += ['Lovbekendtgørelsen opfører denne lov som indarbejdet, men ingen af bestemmelsernes ord er ændret af den.', '',
                    'The consolidation lists this act as incorporated, but none of the words of this text changed.', '']
        art = ', '.join(f'{P.SECT} {n}' for n in an['articles'])
        if keys:
            trailers.append('Evidence: the amending article (' + (art or 'none read') + f' of {lm["label"]}) names ' +
                            ', '.join(labels))
        if an['note']:
            msg += [f'Lovbekendtgørelsens note [{an["note_index"]}] siger at loven vedrører: ' +
                    ', '.join(ch['cur']['units'][k]['label'] if k in ch['cur']['units'] else k for k in an['note']) + '.', '']
            trailers.append(f'Evidence: endnote [{an["note_index"]}] of the consolidation names the provisions this act changed')
        if an['sentence']:
            msg += ['Ikrafttræden læst i den ændrende lov:', '', f'> {an["sentence"]}', '',
                    'Commencement read from the amending act, quoted above.', '']
            trailers.append('Evidence: commencement clause of the amending act')
        if an['quoted_day'] and an['day'] and an['quoted_day'] != an['day']:
            msg += [f'Bemærkning: lovbekendtgørelsen citerer ikrafttrædelsesbestemmelsen med dagen {P.long_day(an["quoted_day"])}; '
                    'lovens egen tekst bruges.', '']
            trailers.append(f'Date-note: the consolidation quotes the commencement clause with {an["quoted_day"]}; the act’s own text is used')
        for s in an['applies']:
            msg += [f'Virkning: {s}', '']
            trailers.append(f'Applies: {s}')
        notes = [ch['why'][k] for k in keys if '; day ' in ch['why'][k]]
        if notes or (not keys and an['day'] is None):
            kinds = {n.split('; day ')[1] for n in notes} | ({'undated'} if (not keys and an['day'] is None) else set())
            what = {'undated': 'dagen er ikke læst i loven; dagen for lovbekendtgørelsen bruges',
                    'late': 'loven træder i kraft før forrige udgaves dag; forrige udgaves dag bruges'}
            msg += [f'Bemærkning: {what[k]}.' for k in sorted(kinds)] + ['']
            trailers += [f'Date-note: {k}' for k in sorted(kinds)]
        trailers += doc_trailers(lm)
        trailers.append(f'In-force: {day}')
        if keys:
            trailers.append('Affecting: ' + ', '.join(f'{b["label"]} {l}' for l in labels))
        trailers.append(f'Source: {lm["url"]}')
    elif kind == 'candidates':
        author = PUBLISHER
        cands = c['grp'].split(':', 1)[1].split(',')
        keys = units_of(ch, c['grp'], day)
        labels, lst = listing(ch, keys)
        names = ', '.join(b['laws'][l]['label'] for l in cands)
        msg = [f'{short}: {", ".join(labels) if len(labels) < 5 else str(len(labels)) + " bestemmelser"} (flere love)', '',
               f'Flere love, {names}, nævner disse bestemmelser i lovbekendtgørelsens noter eller i deres ændringsartikler.',
               'Lovbekendtgørelsen viser kun resultatet, så ændringen er ikke tilskrevet nogen af dem.', ''] + lst + [''] + [
               f'{names} all name these provisions in the consolidation’s endnotes or in their amending articles. The',
               'consolidation shows only the result, so the change is credited to none of them.', '']
        msg += [f'- {b["laws"][l]["label"]}: {b["laws"][l]["title"]}' for l in cands] + ['']
        early = [l for l in cands if ch['analyses'][l]['early']]
        if early:
            msg += ['Heraf trykt før ikrafttræden (printed before taking effect): ' +
                    ', '.join(f'{b["laws"][l]["label"]} ({ch["analyses"][l]["day"]})' for l in early), '']
        trailers += [f'In-force: {day}', 'Affecting: ' + ', '.join(f'{b["label"]} {l}' for l in labels)]
        trailers += [f'Candidate: {b["laws"][l]["label"]}' for l in cands]
        trailers += [f'Printed-early: {b["laws"][l]["label"]} (in force {ch["analyses"][l]["day"]})' for l in early]
        trailers.append('Evidence: the endnotes or amending articles of each candidate name these provisions; the latest of their commencement days, at most the consolidation’s day, is used')
    elif kind == 'early':
        author = PUBLISHER
        law = c['law']
        lm = b['laws'][law]
        an = ch['analyses'][law]
        keys = units_of(ch, c['grp'], day)
        labels, lst = listing(ch, keys)
        msg = [f'{short}: {", ".join(labels) if labels and len(labels) < 6 else str(len(labels)) + " bestemmelser"} (trykt før ikrafttræden: {lm["label"]})', '',
               lm['title'], '',
               f'Lovbekendtgørelsen indarbejder {lm["label"]}, som først træder i kraft den {P.long_day(an["day"])}, efter',
               'lovbekendtgørelsens egen dag. Ændringen er trykt før sin ikrafttræden og tilskrives ikke loven; den står her',
               'fra lovbekendtgørelsens dag, som Nalunaarutit udgiver den.', ''] + lst + ([''] if lst else []) + [
               f'The consolidation incorporates {lm["label"]}, which takes effect only on {an["day"]}, after the',
               'consolidation’s own day. The change is printed before it takes effect and is not credited to the act; it',
               'stands here from the consolidation’s day, as Nalunaarutit publishes it.', '']
        if an['sentence']:
            msg += ['Ikrafttræden læst i den ændrende lov:', '', f'> {an["sentence"]}', '']
        trailers += [f'In-force: {day}', f'Printed-early: {lm["label"]} (in force {an["day"]})',
                     'Affecting: ' + (', '.join(f'{b["label"]} {l}' for l in labels) if labels else 'none'),
                     'Evidence: commencement clause of the amending act, quoted above; the consolidation prints the change',
                     f'Source: {lm["url"]}']
    else:   # consolidation: editorial parts, layout-only changes and anything nothing explains
        author = PUBLISHER
        v = ch['cur']
        d = v['doc']
        unex = ch['groups'].get(('unexplained', ch['from']), [])
        lay = ch['groups'].get(('layout', ch['from']), [])
        keys = sorted(ch['groups'].get(('publisher', ch['from']), []) + unex + lay, key=P.unit_order)
        labels, lst = listing(ch, keys)
        msg = [f'{short}: {d["label"]} (lovbekendtgørelse)', '',
               f'{d["title"]}', '',
               'Lovbekendtgørelsen genudgiver loven med de ændringer den indarbejder. Denne commit indeholder dens egne dele',
               '(indledning, citerede ikrafttrædelsesbestemmelser, underskrifter, noter)' +
               (', ændringer af linjeskift alene' if lay else '') +
               (' og ændringer som ingen note eller ændringsartikel forklarer:' if unex else ':'), ''] + lst + ['',
               'The consolidation republishes the act with the changes it incorporates. This commit holds its own parts',
               '(opening words, quoted commencement clauses, signatures, notes)' + (', changes of paragraph breaks alone' if lay else '') +
               (' and changes no endnote or amending article explains.' if unex else '.'), '']

        def lab(k):
            return v['units'][k]['label'] if k in v['units'] else ch['prev']['units'][k]['label']
        if lay:
            msg += ['Kun linjeskift ændret, ingen ord (layout only): ' + ', '.join(lab(k) for k in sorted(lay, key=P.unit_order)) + '.', '']
        if unex:
            msg += ['Ikke tilskrevet nogen lov (unexplained): ' + ', '.join(lab(k) for k in sorted(unex, key=P.unit_order)) + '.', '']
        trailers += [f'In-force: {ch["from"]}', 'Affecting: ' + ', '.join(f'{b["label"]} {l}' for l in labels) if labels else 'Affecting: none',
                     'Version-acts: ' + (', '.join(b['laws'][l]['label'] for l in ch['laws']) if ch['laws'] else 'none')]
        if lay:
            trailers.append('Layout-only: ' + ', '.join(lab(k) for k in sorted(lay, key=P.unit_order)))
        if unex:
            trailers.append('Unexplained: ' + ', '.join(lab(k) for k in sorted(unex, key=P.unit_order)))
        trailers += doc_trailers(d)
        signed = next((P.danish_day(l) for l in (v['units'].get('slut') or {}).get('lines', []) if P.SIGNATURE.match(l)), None)
        if signed and signed != d['enacted']:
            trailers.append(f'Signed: {signed}')
        trailers.append(f'Source: {d["url"]}')
    trailers.append(f'Consolidated: {ch["url"]}')
    if day < '1970-01-01':
        msg += PRE_1970
    return author, msg, trailers, keys


def write_repo(repo: Path, built: list[dict], docs: Path, today: str):
    remote = None
    if (repo / '.git').exists():
        out = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=repo, capture_output=True, text=True)
        remote = out.stdout.strip() or None

    def force(fn, path, _exc):
        os.chmod(path, 0o700)
        fn(path)
    if repo.exists():
        for p in repo.iterdir():
            shutil.rmtree(p, onexc=force) if p.is_dir() else p.unlink()
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'core.autocrlf', 'false')
    if remote:
        git(repo, 'remote', 'add', 'origin', remote)
    seq = [0]
    tags: dict[str, str] = {}
    law_days: dict[str, list[tuple[str, str]]] = {}
    log = []
    for day, ai, _, _, c in plan_commits(built):
        b = c['b']
        slug = b['act']['slug']
        if c['kind'] == 'start':
            for key, u in b['versions'][0]['units'].items():
                write_unit(repo, slug, key, u)
            author, msg, trailers = start_message(b, day)
            keys = list(b['versions'][0]['units'])
            tagdoc = b['laws'][b['key']]
        else:
            author, msg, trailers, keys = change_message(b, c)
            for k in keys:
                write_unit(repo, slug, k, c['ch']['cur']['units'].get(k))
            if c['kind'] == 'law':
                tagdoc = b['laws'][c['law']]
            elif c['kind'] == 'consolidation':
                tagdoc = c['ch']['cur']['doc']
            else:
                tagdoc = None
        git(repo, 'add', '-A')
        when = commit_date(day, seq)
        env = {**os.environ, 'GIT_AUTHOR_NAME': author[0], 'GIT_AUTHOR_EMAIL': author[1], 'GIT_AUTHOR_DATE': when,
               'GIT_COMMITTER_NAME': COMMITTER[0], 'GIT_COMMITTER_EMAIL': COMMITTER[1], 'GIT_COMMITTER_DATE': when}
        git(repo, 'commit', '-q', '--allow-empty', '--cleanup=verbatim', '-F', '-', env=env,
            input='\n'.join(msg).rstrip('\n') + '\n\n' + '\n'.join(trailers) + '\n')
        head = git(repo, 'rev-parse', 'HEAD').strip()
        tags[f'{slug}/{day}'] = head
        if tagdoc:
            days = law_days.setdefault(tag_of(tagdoc), [])
            if days and days[-1][0] == day:
                days[-1] = (day, head)
            else:
                days.append((day, head))
        log.append({'day': day, 'slug': slug, 'kind': c['kind'], 'author': author[0], 'units': len(keys),
                    'clamped': day < '1970-01-01', 'keys': keys})
    for t, days in law_days.items():
        if len(days) == 1:
            tags[t] = days[0][1]
        else:
            for day, head in days:
                tags[f'{t}/{day}'] = head
    for name in sorted(tags):
        git(repo, 'tag', '-f', name, tags[name])
    for p in sorted(docs.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            dest = repo / p.relative_to(docs)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(p.read_bytes())
    for name in ('build.py', 'glfetch.py', 'glparse.py', 'reproduce.py', 'check_repo.py', 'test_repo.py'):
        (repo / 'tools' / name).write_bytes((HERE / name).read_bytes())
    write_tables(repo, built)
    from reproduce import write_manifest, write_reproduce
    write_manifest(repo, built, today)
    write_reproduce(repo, built, log, tags, glfetch.REQUESTS, today)
    git(repo, 'add', '-A')
    when = commit_date(today, seq)
    env = {**os.environ, 'GIT_AUTHOR_NAME': COMMITTER[0], 'GIT_AUTHOR_EMAIL': COMMITTER[1], 'GIT_AUTHOR_DATE': when,
           'GIT_COMMITTER_NAME': COMMITTER[0], 'GIT_COMMITTER_EMAIL': COMMITTER[1], 'GIT_COMMITTER_DATE': when}
    git(repo, 'commit', '-q', '-m', 'Dokumentation, tabeller, værktøjer og REPRODUCE.md', env=env)
    return log, tags


def write_tables(repo: Path, built: list[dict]):
    out = []
    for b in built:
        first = b['versions'][0]
        lm = b['laws'][b['key']]
        out.append({'lov': b['act']['short'], 'nummer': lm['label'], 'titel': lm['title'], 'type': lm['kind'],
                    'dateret': lm['enacted'], 'ikraft': first['from'], 'bestemmelser': len(first['units']),
                    'bemaerkning': 'som vedtaget', 'status': lm['status'], 'kilde': lm['url']})
        for ch in b['changes']:
            for (grp, day), keys in sorted(ch['groups'].items(), key=lambda x: (x[0][1], x[0][0])):
                if grp in ('unexplained', 'publisher', 'layout') or grp.startswith('candidates:'):
                    continue
                early = grp.startswith('early:')
                lm = b['laws'][grp[6:] if early else grp]
                out.append({'lov': b['act']['short'], 'nummer': lm['label'], 'titel': lm['title'], 'type': lm['kind'],
                            'dateret': lm['enacted'], 'ikraft': ch['analyses'][grp[6:]]['day'] if early else day,
                            'bestemmelser': len(keys), 'bemaerkning': 'trykt før ikrafttræden' if early else '',
                            'status': lm['status'], 'kilde': lm['url']})
            d = ch['cur']['doc']
            out.append({'lov': b['act']['short'], 'nummer': d['label'], 'titel': d['title'], 'type': d['kind'],
                        'dateret': d['enacted'], 'ikraft': ch['from'], 'bestemmelser': len(ch['cur']['units']),
                        'bemaerkning': 'lovbekendtgørelse', 'status': d['status'], 'kilde': d['url']})
    out.sort(key=lambda r: (r['ikraft'], r['lov'], r['type'] == 'lovbekendtgørelse', r['nummer']))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(out[0]), lineterminator='\n')
    w.writeheader()
    w.writerows(out)
    (repo / 'love.csv').write_text(buf.getvalue(), encoding='utf-8', newline='\n')
    for b in built:
        act = b['act']
        last = b['versions'][-1]
        counts: dict[str, int] = {}
        lastday: dict[str, str] = {}
        for ch in b['changes']:
            for (grp, day), keys in ch['groups'].items():
                for k in keys:
                    counts[k] = counts.get(k, 0) + 1
                    lastday[k] = max(lastday.get(k, ''), day)
        lines = [f'# {b["title"]}', '', f'{b["label"]} · <{b["laws"][b["key"]]["url"]}>', '',
                 f'{len(b["versions"])} versioner i Nalunaarutit, gældende fra {b["versions"][0]["from"]} (seneste fra {last["from"]}).', '',
                 '| Bestemmelse | Fil | Ændringer | Senest ændret |', '| --- | --- | ---: | --- |']
        for k in sorted(last['units'], key=P.unit_order):
            u = last['units'][k]
            lines.append(f'| {u["label"]} | [{k}.md]({k}.md) | {counts.get(k, 0)} | {lastday.get(k, "")} |')
        (repo / act['slug'] / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def data_day() -> str:
    c = glfetch.CACHE
    files = [p for p in c.iterdir() if p.name != '.gitignore' and not p.name.startswith(('survey', 'probe', 'sitemap-raw'))] if c.exists() else []
    if not files:
        return dt.date.today().isoformat()
    return dt.date.fromtimestamp(max(p.stat().st_mtime for p in files)).isoformat()


def build_all(offline: bool) -> list[dict]:
    paths = sitemap(offline)
    return [build_act(a, offline, paths) for a in ACTS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=str(ROOT.parent / 'greenland-law'))
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--today', default=None)
    ap.add_argument('--verify-rebuild', action='store_true')
    args = ap.parse_args()
    if args.verify_rebuild:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([os.sys.executable, '-X', 'utf8', str(HERE / 'build.py'), '--offline', '--repo', tmp]
                                 + (['--today', args.today] if args.today else []), capture_output=True, text=True)
            if out.returncode:
                raise SystemExit(out.stderr)

            def hashes(r):
                log = git(Path(r), 'log', '--format=%H', 'main').split()
                tags = dict(l.split(' ', 1)[::-1] for l in git(Path(r), 'show-ref', '--tags').split('\n') if l)
                return log, tags
            a, b = hashes(args.repo), hashes(tmp)
            rec = {'identical': a[0][1:] == b[0][1:] and a[1] == b[1], 'history_tip': a[0][1], 'commits': len(a[0]) - 1,
                   'tags': len(a[1]), 'main_identical': a[0][0] == b[0][0], 'main': a[0][0], 'rebuilt_main': b[0][0]}
            print(json.dumps(rec, indent=1))
            p = HERE / 'verification.json'
            ver = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
            ver['rebuild'] = {k: rec[k] for k in ('identical', 'history_tip', 'commits', 'tags')}
            p.write_text(json.dumps(ver, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
            for f in Path(tmp).rglob('*'):
                os.chmod(f, 0o700)
            raise SystemExit(0 if rec['identical'] else 1)
    built = build_all(args.offline)
    today = args.today or data_day()
    for b in built:
        n = sum(len(ks) for ch in b['changes'] for ks in ch['groups'].values())
        print(f'{b["act"]["slug"]}: {len(b["versions"])} versions {b["versions"][0]["from"]}..{b["versions"][-1]["from"]}, '
              f'{len(b["versions"][-1]["units"])} units, {n} unit changes, {len(b["problems"])} not credited to one act')
        for p in b['problems']:
            print('   ', p)
    if os.environ.get('GL_DRY'):
        for b in built:
            for ch in b['changes']:
                print(ch['from'], 'laws', [b['laws'][l]['label'] for l in ch['laws']])
                for (grp, day), keys in sorted(ch['groups'].items(), key=lambda x: (x[0][1], x[0][0])):
                    print('   ', day, grp, len(keys), keys[:12])
                for u in sorted(ch['why'], key=P.unit_order):
                    print('      ', u, '->', ch['cause'][u], '|', ch['why'][u])
        return
    log, tags = write_repo(Path(args.repo), built, HERE / 'repo', today)
    print(f'repo: {len(log)} commits + 1 documentation commit, {len(tags)} tags -> {args.repo}')


if __name__ == '__main__':
    main()

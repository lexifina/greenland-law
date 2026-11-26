"""Greenland breadth build: every legislative text on Nalunaarutit as one folder per act, one file per section,
one commit per official version (as passed, each consolidation), amending acts and repeals on their in-force day.

Usage: python -X utf8 gl_breadth.py plan            -> work/plan.json + work/plan-report.txt
       python -X utf8 gl_breadth.py stream PART     -> fast-import onto refs/heads/<branch> (PART: gl | rigs | all)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

GL = Path(r'C:\Users\alany\Documents\lexifina\scripts\greenland-law')
sys.path.insert(0, str(GL))
import glparse as P  # noqa: E402  (read-only reuse of the published builder's page reader)

from lxml import html as lhtml  # noqa: E402

CACHE = GL / '.cache'
WORK = Path(r'C:\Users\alany\Documents\greenland-work')
SM = WORK / 'dl' / 'sm.xml'
REPO = Path(r'C:\Users\alany\Documents\greenland-law')
SITE = 'https://nalunaarutit.gl'
COMMITTER = ('Lexifina', 'greenland-law@lexifina.com')
PUBLISHER = ('Nalunaarutit (Grønlands Selvstyre)', 'nalunaarutit@nalunaarutit.invalid')
MONTHS = P.MONTHS
import os
CUTOFF = int(os.environ.get('GL_CUTOFF', '0'))
DONE = WORK / 'done.json'
RENAMED: dict[str, str] = {}  # build folder name -> folder in the type/year layout
MON = '|'.join(MONTHS)

# ---------------------------------------------------------------- kinds

KIND_RULES = [  # (regex on title start, family, folder word, label word)
    (r'selvstyrets\s+lovbekendtg', 'lbk', None, 'Selvstyrets lovbekendtgørelse'),
    (r'(hjemmestyrets|landsstyrets)\s+lovbekendtg', 'lbk', None, 'Lovbekendtgørelse'),
    (r'bekendtgørelse\s+af\s+(lov|landstingslov|landstingsforordning|inatsisartutlov)', 'lbk', None, 'Lovbekendtgørelse'),
    (r'lovbekendtgørelse', 'lbk', None, 'Lovbekendtgørelse'),
    (r'(selvstyrets|hjemmestyrets)\s+bekendtgørelse\s+af\s+(lov|landstingslov|landstingsforordning|inatsisartutlov|inatsisartutforordning|inasisartutlov)',
     'lbk', None, 'Selvstyrets lovbekendtgørelse'),
    (r'inatsisartutlov', 'gl-lov', 'inatsisartutlov', 'Inatsisartutlov'),
    (r'landstingslov', 'gl-lov', 'landstingslov', 'Landstingslov'),
    (r'inatsisartutforordning', 'gl-forordning', 'inatsisartutforordning', 'Inatsisartutforordning'),
    (r'landstingsforordning', 'gl-forordning', 'landstingsforordning', 'Landstingsforordning'),
    (r'landsrådsvedtægt', 'gl-vedtaegt', 'landsraadsvedtaegt', 'Landsrådsvedtægt'),
    (r'(selvstyrets|hjemmestyrets|landsstyrets|landstingets|grønlands hjemmestyres|landstings|landstinget)\w*\s+bekendtg', 'gl-bkg', 'bekendtgoerelse', 'Bekendtgørelse'),
    (r'(kommunal|politi)?vedtægt', 'vedtaegt', 'vedtaegt', 'Vedtægt'),
    (r'forretningsorden', 'forretningsorden', 'forretningsorden', 'Forretningsorden'),
    (r'regulativ', 'regulativ', 'regulativ', 'Regulativ'),
    (r'kongelig\s+anordning|anordning', 'anordning', 'anordning', 'Anordning'),
    (r'lov\b', 'lov', 'lov', 'Lov'),
    (r'(\w+\s+){0,3}bekendtg', 'bkg', 'bekendtgoerelse', 'Bekendtgørelse'),
    (r'(\w+\s+){0,2}\w*lov(en)?\b', 'lov', 'lov', 'Lov'),
    (r'selvstyre\w*\s+lovbekendtg', 'lbk', None, 'Selvstyrets lovbekendtgørelse'),
    (r'\w*bekendtgørelse', 'bkg', 'bekendtgoerelse', 'Bekendtgørelse'),
    (r'.{0,40}vedtægt', 'vedtaegt', 'vedtaegt', 'Vedtægt'),
    (r'.{0,40}regulativ', 'regulativ', 'regulativ', 'Regulativ'),
    (r'påbud', 'paabud', 'paabud', 'Påbud'),
]
EXCLUDE = re.compile(r'^(\S+\s+)?(cirkulære|cirkulærskrivelse|vejledning|retningslinje|takstblad|tekstanmærkning|åbent brev|brev|'
                     r'oversigt|lovoversigt|skrivelse|meddelelse|redegørelse)', re.I)
REF = re.compile(r'(Inatsisartutlov|Landstingslov|Inatsisartutforordning|Landstingsforordning|lovbekendtgørelse|'
                 r'bekendtgørelse|anordning|lov)\s+nr\.?\s*(\d+)\s*(?:,|af)?\s*(?:den\s+)?(\d{1,2})\.?\s*(' + MON + r')\s+(\d{4})',
                 re.I)


def ref_family(word: str, section: str) -> str:
    w = word.lower()
    if w in ('inatsisartutlov', 'landstingslov'):
        return 'gl-lov'
    if w in ('inatsisartutforordning', 'landstingsforordning'):
        return 'gl-forordning'
    if w == 'lovbekendtgørelse':
        return 'lbk'
    if w == 'bekendtgørelse':
        return 'gl-bkg' if section == 'gl' else 'bkg'
    if w == 'anordning':
        return 'anordning'
    return 'lov' if section != 'gl' else 'lov'


def classify(title: str) -> tuple[str, str | None, str] | None:
    t = title.strip()
    if EXCLUDE.match(t):
        return None
    for rx, fam, word, label in KIND_RULES:
        if re.match(rx, t, re.I):
            return fam, word, label
    return None


# ---------------------------------------------------------------- pages

def cached(url: str) -> bytes | None:
    p = CACHE / hashlib.sha256(url.encode()).hexdigest()[:32]
    return p.read_bytes() if p.exists() else None


def slug_day(path: str) -> str | None:
    m = re.search(r'(\d{2})[_-](\d{2})[_-](\d{4})$', path)
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


TOKEN = re.compile(r'\w+|[^\w\s]')


def official_words(raw_html: str, title_override: str | None = None) -> list[str]:
    doc = lhtml.fromstring(raw_html)
    main = doc.get_element_by_id('main')
    title = title_override if title_override is not None else next(iter(main.iter('h1', 'h2', 'h3'))).text_content()
    rt = [d for d in main.iter('div') if 'richtext' in (d.get('class') or '')][0]

    def text(e) -> str:
        if not isinstance(e.tag, str):
            return e.tail or ''
        gap = ' ' if e.tag in ('div', 'br', 'p', 'td', 'th', 'tr', 'table', 'li', 'ul', 'ol',
                               'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr') else ''
        return gap + (e.text or '') + ''.join(text(c) for c in e) + gap + (e.tail or '')
    body = title + ' ' + text(rt)[:-len(rt.tail or '') or None]
    return TOKEN.findall(re.sub('[\u00ad\u200b\ufeff]', '', body))


def repo_words(text: str) -> list[str]:
    lines = []
    for line in text.split('\n'):
        line = re.sub(r'^\s*(#+ |- )', '', line)
        lines.append(line.replace(' | ', ' '))
    return TOKEN.findall(' '.join(lines))


def units_for(pg: dict, raw: str, title: str) -> tuple[dict[str, str], str]:
    """Files of one version: one per section when the split reproduces the page word for word, else one file."""
    try:
        parsed = P.read_units(pg)
        units = {k: u['text'] for k, u in parsed['units'].items()}
        units['titel'] = title + '\n'
        if not any(k.startswith('par-') for k in units):
            raise SystemExit('no sections')
        if any(k.endswith('-dup') for k in units):
            raise SystemExit('duplicate sections')
        ordered = ''.join(units[k] for k in sorted(units, key=P.unit_order))
        if official_words(raw, title) == repo_words(ordered):
            return units, 'sections'
    except (SystemExit, Exception):
        pass
    text = title + '\n\n' + '\n\n'.join(line for _, line in pg['lines']) + '\n'
    return {'hele-teksten': text}, 'single'


SUBJ = r'(?:loven|denne lov|inatsisartutloven|landstingsloven|forordningen|landstingsforordningen|inatsisartutforordningen|' \
       r'bekendtgørelsen|denne bekendtgørelse|anordningen|denne anordning|vedtægten|regulativet|forretningsordenen|' \
       r'lovbekendtgørelsen|ændringerne|bestemmelserne|reglerne|denne \w+|\w+(?:loven|forordningen|bekendtgørelsen))'
COMM = re.compile(r'\b' + SUBJ + r'[^.]{0,80}?træder\s+i\s+kraft\s+([^.;]{0,120})', re.I)


def commencement(lines: list[str], designated: str) -> tuple[str, str]:
    for line in lines:
        if line[:1] in P.QUOTES:
            continue
        m = COMM.search(line)
        if not m:
            continue
        rest = line[m.start(1):m.start(1) + 120]
        day = P.danish_day(rest)
        dm = P.DAY.search(rest)
        sent = P.clean(line[m.start():m.start(1) + (dm.end() if dm else 60)])[:200]
        if day:
            return day, f'commencement provision: "{sent}"'
        if re.search(r'dagen\s+efter', rest, re.I):
            d = (dt.date.fromisoformat(designated) + dt.timedelta(days=1)).isoformat()
            return d, f'commencement provision: "{sent}" (the day after the designation day {designated})'
        if re.search(r'straks|ved\s+bekendtgørelsen|fra\s+underskrift', rest, re.I):
            return designated, f'commencement provision: "{sent}" (the designation day)'
    return designated, 'designation day on Nalunaarutit (no dated commencement provision found in the text)'


def read_doc(url: str) -> dict | None:
    raw = cached(url)
    if raw is None:
        return {'url': url, 'missing': 'not fetched'}
    if not raw:
        return {'url': url, 'missing': '404'}
    html = raw.decode('utf-8')
    try:
        pg = P.page(html)
    except Exception:
        return {'url': url, 'missing': 'no text body on the page (no HTML text; PDF or empty)'}
    path = url.replace(SITE, '').split('?')[0]
    section = {'Groenlandsk-lovgivning': 'gl', 'Rigslovgivning': 'rigs', 'International-lovgivning': 'int'}.get(path.split('/')[1])
    title = P.clean(pg['title'])
    year = int(path.split('/')[2]) if path.split('/')[2].isdigit() else None
    day = pg['site_day'] or slug_day(path) or (f'{year}-01-01' if year else None)
    texts = [t for _, t in pg['lines']]
    return {'url': url, 'path': path, 'section': section, 'title': title, 'number': pg['number'], 'site_day': day,
            'year': year, 'status': pg['status'], 'header_kind': pg['kind'], 'lines': texts, 'pg': pg, 'raw': html}


# ---------------------------------------------------------------- plan

def folder_name(doc: dict, fam_word: str) -> str:
    y = doc['year'] or doc['site_day'][:4]
    n = doc['number']
    base = f'{fam_word}-{y}-{n}' if n else f'{fam_word}-{doc["site_day"]}'
    if doc['section'] == 'rigs':
        return 'rigslovgivning/' + base
    if doc['section'] == 'int':
        return 'international/' + base
    return base


def make_plan() -> dict:
    xml = SM.read_text(encoding='utf-8')
    urls = sorted({l for l in re.findall(r'<loc>([^<]+)</loc>', xml) if l.endswith('sc_lang=da')
                   and re.search(r'/(Groenlandsk-lovgivning|Rigslovgivning|International-lovgivning)/', l)})
    docs, held, excluded = [], [], []
    for u in urls:
        if CUTOFF and '/Groenlandsk-lovgivning/' in u and int(u.split('/')[4]) >= CUTOFF:
            continue
        if CUTOFF and '/Groenlandsk-lovgivning/' not in u:
            continue
        d = read_doc(u)
        if 'missing' in d:
            held.append({'url': u, 'reason': d['missing']})
            continue
        c = classify(d['title'])
        if d['section'] == 'int':
            c = ('int', 'traktat', 'Traktat')
        if c is None:
            excluded.append({'url': u, 'title': d['title']})
            continue
        d['family'], d['word'], d['label_word'] = c
        if d['family'] in ('gl-bkg', 'bkg') and d['section'] == 'rigs':
            d['family'] = 'bkg'
        elif d['family'] == 'bkg':
            d['family'] = 'gl-bkg'
        docs.append(d)
    # cited designation days: (family, nr, year) -> Counter(day)
    cited: dict[tuple, Counter] = defaultdict(Counter)
    for d in docs:
        for line in d['lines'][:60]:
            for m in REF.finditer(line):
                fam = ref_family(m.group(1), d['section'])
                day = f'{int(m.group(5)):04d}-{MONTHS[m.group(4).lower()]:02d}-{int(m.group(3)):02d}'
                cited[(d['section'] if d['section'] != 'int' else 'rigs', fam, int(m.group(2)), int(m.group(5)))][day] += 1
    by_key: dict[tuple, dict] = {}
    for d in docs:
        sec = d['section'] if d['section'] != 'int' else 'int'
        if d['number'] and d['year']:
            key = (sec, d['family'], d['number'], d['year'])
            c = cited.get(key)
            d['enacted'] = c.most_common(1)[0][0] if c else d['site_day']
            d['enacted_basis'] = 'as cited by other texts on Nalunaarutit' if c else 'date shown on Nalunaarutit'
            if key in by_key:
                key = key + (d['path'],)
            by_key[key] = d
        else:
            d['enacted'] = d['site_day']
            d['enacted_basis'] = 'date shown on Nalunaarutit'
        d['key'] = (sec, d['family'], d['number'], d['year'])

    def lookup(section: str, word: str, nr: int, year: int):
        fam = ref_family(word, section)
        for fam_try in ([fam] if fam != 'lov' else ['lov', 'gl-lov']):
            d = by_key.get((section, fam_try, nr, year))
            if d is not None:
                return d
        return None

    def first_ref(d: dict, pattern_first: bool):
        for line in d['lines'][:12]:
            for m in REF.finditer(line):
                return m
        return None

    groups: dict[str, dict] = {}
    events = []
    amend_rx = re.compile(r'\bom\s+ændring(?:er)?\s+af\b|\bændring\s+af\s+(visse|forskellige)', re.I)
    bases, cons, amends = [], [], []
    for d in docs:
        t = d['title'].lower()
        if d['family'] == 'lbk' or re.match(r'(selvstyrets|hjemmestyrets)\s+bekendtgørelse\s+af\s+(selvstyrets|hjemmestyrets|landsstyrets)?\s*bekendtgørelse', t):
            cons.append(d)
        elif amend_rx.search(t) and d['family'] != 'int':
            amends.append(d)
        else:
            bases.append(d)
    for d in bases:
        f = folder_name(d, d['word'])
        while f in groups:
            f += '-b'
        d['folder'] = f
        groups[f] = {'folder': f, 'base': d, 'versions': [], 'amendments': [], 'status': d['status']}
    unresolved_cons, unresolved_amends = [], []
    for d in cons:
        m = first_ref(d, True)
        target = lookup(d['section'] if d['section'] != 'int' else 'rigs', m.group(1), int(m.group(2)), int(m.group(5))) if m else None
        if target is None or 'folder' not in target:
            # a consolidation whose base act is not on the site: its own folder, named after the base it cites
            word = (m.group(1).lower() if m else 'lovbekendtgoerelse').replace('ø', 'oe').replace('æ', 'ae').replace('å', 'aa')
            if m:
                f = (f'{word}-{m.group(5)}-{m.group(2)}')
                f = ('rigslovgivning/' + f) if d['section'] == 'rigs' else f
            else:
                f = folder_name(d, 'lovbekendtgoerelse')
            if f not in groups:
                groups[f] = {'folder': f, 'base': None, 'versions': [], 'amendments': [], 'status': d['status'],
                             'cited_base': m.group(0) if m else None}
            unresolved_cons.append(d['url'])
            groups[f]['versions'].append(d)
            d['folder'] = f
        else:
            groups[target['folder']]['versions'].append(d)
            d['folder'] = target['folder']
    for d in amends:
        targets = []
        for line in d['lines'][:400]:
            if re.search(r'foretages\s+følgende|ændres\s+således|foretages\s+følgende\s+ændring', line, re.I) or re.match(r'^I\s', line):
                for m in REF.finditer(line):
                    t = lookup(d['section'] if d['section'] != 'int' else 'rigs', m.group(1), int(m.group(2)), int(m.group(5)))
                    if t is not None and t.get('folder') and t['folder'] not in targets:
                        targets.append(t['folder'])
        if not targets:
            m = first_ref(d, True)
            t = lookup(d['section'], m.group(1), int(m.group(2)), int(m.group(5))) if m else None
            if t is not None and t.get('folder'):
                targets.append(t['folder'])
        if not targets:
            # an amending act whose amended act is not on the site: kept as a text of its own
            f = folder_name(d, d['word'])
            while f in groups:
                f += '-b'
            d['folder'] = f
            groups[f] = {'folder': f, 'base': d, 'versions': [], 'amendments': [], 'status': d['status']}
            unresolved_amends.append(d['url'])
            continue
        d['targets'] = targets
        for f in targets:
            groups[f]['amendments'].append(d)
    # repeals: "ophæves" sentences naming an act
    repeals = []
    for d in docs:
        for line in d['lines']:
            if line[:1] in P.QUOTES or not re.search(r'\bophæves\b', line, re.I):
                continue
            for sent in re.split(r'(?<=[a-zæøå0-9)])\.\s+(?=[A-ZÆØÅ§])', line):
                if not re.search(r'\bophæves\b', sent, re.I):
                    continue
                if re.search(r'indtil|forbliver|videreføres|ophæves ikke|\bdog\b|§|stk\.|kapitel|afløses|fortsat|'
                             r'foretages|ændring', sent, re.I):
                    continue
                if not re.match(r'^(Samtidig|Endvidere|Fra samme tidspunkt|Fra samme dato)?\s*ophæves\b', sent, re.I) and \
                        not re.search(r'\bophæves\.?\s*$', sent, re.I):
                    continue
                for m in REF.finditer(sent):
                    before = sent[:m.start()]
                    if re.search(r'(§\s*\d|stk\.|kapitel|afsnit|bilag|nr\.\s*\d+\s*(,|og))[^,;]{0,40}\bi\s*$', before, re.I) or re.search(r'\bi\s*$', before):
                        continue
                    t = lookup(d['section'] if d['section'] != 'int' else 'rigs', m.group(1), int(m.group(2)), int(m.group(5)))
                    if t is not None and t.get('folder') and t is not d and t['folder'] in groups and groups[t['folder']]['base'] is t:
                        repeals.append((d, t['folder'], P.clean(sent)[:300]))
    for f in ('inatsisartutlov-2010-9', 'landstingslov-1992-20'):  # already published with full history (kirken/, havneafgift/)
        groups.pop(f, None)
    # since 2026-11-26 the folders live in type and year folders (data/paths.json; new ones by the same rule)
    moved_file = REPO / 'data' / 'paths.json'
    if moved_file.exists():
        moved = json.loads(moved_file.read_text(encoding='utf-8'))

        def place(old: str, g: dict) -> str:
            if old in moved:
                return moved[old]
            base = old.rsplit('/', 1)[-1]
            word = re.match(r'([a-z]+)-', base).group(1)
            year = re.search(r'(\d{4})', base).group(1)
            d0 = g['base'] or g['versions'][-1]
            st = (g['versions'][-1]['status'] if g['versions'] else d0['status'])
            sub = f'ophaevede/{year}' if st == 'Ophævet' else year
            rigs = {'lov': 'love', 'anordning': 'anordninger', 'bekendtgoerelse': 'bekendtgoerelser',
                    'lovbekendtgoerelse': 'lovbekendtgoerelser', 'forretningsorden': 'forretningsordener'}
            gl = {'inatsisartutlov': 'inatsisartutlove', 'landstingslov': 'landstingslove', 'lov': 'inatsisartutlove',
                  'landstingsforordning': 'landstingsforordninger', 'inatsisartutforordning': 'inatsisartutforordninger',
                  'bekendtgoerelse': 'bekendtgoerelser', 'vedtaegt': 'vedtaegter', 'regulativ': 'regulativer',
                  'paabud': 'paabud', 'landsraadsvedtaegt': 'landsraadsvedtaegter',
                  'forretningsorden': 'forretningsordener', 'lovbekendtgoerelse': 'lovbekendtgoerelser'}
            if old.startswith('rigslovgivning/'):
                return f'rigslovgivning/{rigs.get(word, word)}/{sub}/{base}'
            if old.startswith('international/'):
                return f'international/{sub}/{base}'
            return f'{gl.get(word, word)}/{sub}/{base}'
        ren = {f: place(f, g) for f, g in groups.items()}
        for f, g in groups.items():
            g['old_folder'] = f
            g['folder'] = ren[f]
        groups = {ren[f]: g for f, g in groups.items()}
        repeals = [(d, ren.get(f, f), line) for d, f, line in repeals]
        for d in docs:
            if d.get('folder') in ren:
                d['folder'] = ren[d['folder']]
        RENAMED.update(ren)
    repeals = [r for r in repeals if r[1] in groups]
    return {'docs': docs, 'groups': groups, 'held': held, 'excluded': excluded, 'repeals': repeals,
            'unresolved_cons': unresolved_cons, 'unresolved_amends': unresolved_amends}


# ---------------------------------------------------------------- commits

def nuuk_offset(day: dt.date) -> int:
    def last_sunday(year, month):
        d = (dt.date(year, month + 1, 1) if month < 12 else dt.date(year + 1, 1, 1)) - dt.timedelta(days=1)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)

    def eu_summer(d):
        y = d.year
        if y < 1980:
            return False
        if y == 1980:
            return dt.date(1980, 4, 6) <= d < dt.date(1980, 9, 28)
        return last_sunday(y, 3) <= d < last_sunday(y, 9 if y < 1996 else 10)
    if day < dt.date(2023, 3, 26):
        return -2 if eu_summer(day) else -3
    if day < dt.date(2024, 3, 31):
        return -2
    return -1 if eu_summer(day) else -2


SEQ = [0]


def git_date(day: str) -> str:
    d = dt.date.fromisoformat(day)
    if d.year < 1970:
        SEQ[0] += 1
        return f'{SEQ[0]} +0000'
    off = nuuk_offset(d)
    stamp = int(dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone(dt.timedelta(hours=off))).timestamp())
    return f'{stamp} -0{-off}00'


def label(d: dict) -> str:
    if d.get('number'):
        return f'{d["label_word"]} nr. {d["number"]} af {P.long_day(d["enacted"])}'
    return f'{d["label_word"]} af {P.long_day(d["enacted"])}'


def ident(d: dict) -> tuple[str, str]:
    slug = re.sub(r'[^a-z0-9]+', '-', label(d).lower().replace('ø', 'oe').replace('æ', 'ae').replace('å', 'aa')).strip('-')
    return label(d), f'{slug}@nalunaarutit.invalid'


def amend_file(d: dict) -> str:
    return f'aendringslove/{d["year"]}-{d["number"] or d["site_day"]}.md'


def build_events(plan: dict, part: str) -> list[dict]:
    ev = []
    for f, g in plan['groups'].items():
        sec = 'rigs' if f.startswith(('rigslovgivning/', 'international/')) else 'gl'
        if part != 'all' and sec != part:
            continue
        b = g['base']
        if b is not None:
            day, basis = commencement(b['lines'], b['enacted'])
            ev.append({'day': day, 'prio': 0, 'folder': f, 'doc': b, 'kind': 'act', 'basis': basis})
        for c in g['versions']:
            ev.append({'day': c['site_day'], 'prio': 2, 'folder': f, 'doc': c, 'kind': 'consolidation',
                       'basis': 'designation day of the consolidation (lovbekendtgørelse) on Nalunaarutit'})
        for a in g['amendments']:
            day, basis = commencement(a['lines'], a['enacted'])
            ev.append({'day': day, 'prio': 1, 'folder': f, 'doc': a, 'kind': 'amendment', 'basis': basis})
    seen = set()
    for d, f, line in plan['repeals']:
        sec = 'rigs' if f.startswith(('rigslovgivning/', 'international/')) else 'gl'
        if (part != 'all' and sec != part) or f in seen:
            continue
        seen.add(f)
        day, basis = commencement(d['lines'], d['enacted'])
        ev.append({'day': day, 'prio': 3, 'folder': f, 'doc': d, 'kind': 'repeal', 'basis': basis, 'line': line})
    ev.sort(key=lambda e: (e['day'], e['prio'], e['folder']))
    # a repeal must come after every version of the folder
    last = defaultdict(str)
    for e in ev:
        if e['kind'] != 'repeal':
            last[e['folder']] = max(last[e['folder']], e['day'])
    ev = [e for e in ev if not (e['kind'] == 'repeal' and e['day'] < last[e['folder']])]
    return ev


def folder_readme(g: dict, d: dict, status: str) -> str:
    lines = [f'# {d["title"]}', '', label(d) if g['base'] is not None else (g.get('cited_base') or label(d)), '',
             f'Status på Nalunaarutit: {status or "ikke angivet"}', '', f'Kilde: <{d["url"]}>', '']
    return '\n'.join(lines)


def stream(plan: dict, part: str, branch: str, start: str, out: Path) -> dict:
    ev = build_events(plan, part)
    done = set(json.loads(DONE.read_text(encoding='utf-8'))) if DONE.exists() else set()
    done = {('|'.join([k.split('|', 2)[0], RENAMED.get(k.split('|', 2)[1], k.split('|', 2)[1]), k.split('|', 2)[2]])) for k in done}
    last_done: dict[str, str] = {}
    for e in ev:
        if f"{e['kind']}|{e['folder']}|{e['doc']['url']}" in done and e['kind'] in ('act', 'consolidation'):
            last_done[e['folder']] = max(last_done.get(e['folder'], ''), e['day'])
    late = [e for e in ev if f"{e['kind']}|{e['folder']}|{e['doc']['url']}" not in done
            and e['kind'] in ('act', 'consolidation', 'repeal') and e['day'] < last_done.get(e['folder'], '')]
    (WORK / 'late.json').write_text(json.dumps([{'folder': e['folder'], 'kind': e['kind'], 'day': e['day'],
                                                 'url': e['doc']['url']} for e in late], ensure_ascii=False, indent=1),
                                    encoding='utf-8')
    late_ids = {id(e) for e in late}
    ev = [e for e in ev if f"{e['kind']}|{e['folder']}|{e['doc']['url']}" not in done and id(e) not in late_ids]
    files: dict[str, set[str]] = defaultdict(set)
    tree = subprocess.run(['git', 'ls-tree', '-r', '--name-only', start], cwd=REPO, capture_output=True,
                          text=True, encoding='utf-8', check=True).stdout.split('\n')
    folders = set(plan['groups'])
    for path in tree:
        parts = path.split('/')
        for n in (1, 2, 3, 4, 5):
            if '/'.join(parts[:n]) in folders and len(parts) > n:
                files['/'.join(parts[:n])].add(path)
                break
    new_done = []
    buf = bytearray()
    prev = start
    counts = Counter()
    split_stats = Counter()
    for i, e in enumerate(ev, 1):
        d, f = e['doc'], e['folder']
        g = plan['groups'][f]
        ops: list[tuple[str, str | None]] = []
        if e['kind'] in ('act', 'consolidation'):
            title = P.act_title(d['title']) if e['kind'] == 'consolidation' else d['title']
            units, how = units_for(d['pg'], d['raw'], title)
            split_stats[how] += 1
            new = {f'{f}/{k}.md': v for k, v in units.items()}
            new[f'{f}/README.md'] = folder_readme(g, d, d['status'])
            for p in sorted(files[f] - set(new) - {x for x in files[f] if '/aendringslove/' in x}):
                ops.append((p, None))
            ops += sorted(new.items())
            files[f] = (files[f] - {p for p, v in ops if v is None}) | set(new)
            if e['kind'] == 'act':
                subject = f'{f}: {d["title"]}'
                author = ident(d)
                body = f'{label(d)}, som vedtaget (as passed).\n\nKilde: {d["url"]}\n'
            else:
                subject = f'{f}: {d["title"]} (lovbekendtgørelse)'
                author = PUBLISHER
                incorporated = []
                for line in d['lines'][:6]:
                    for m in REF.finditer(line):
                        incorporated.append(P.clean(m.group(0)))
                body = (f'{label(d)}: the consolidated text as published by Grønlands Selvstyre.\n\n'
                        f'Kilde: {d["url"]}\n')
                if incorporated[1:]:
                    body += '\n' + ''.join(f'Incorporates: {x}\n' for x in incorporated[1:20])
        elif e['kind'] == 'amendment':
            units, how = units_for(d['pg'], d['raw'], d['title'])
            text = '\n'.join(units[k] for k in sorted(units, key=P.unit_order))
            p = f'{f}/{amend_file(d)}'
            ops.append((p, f'<!-- {label(d)}. Kilde: {d["url"]} -->\n\n' + text))
            files[f].add(p)
            subject = f'{f}: {d["title"]}'
            author = ident(d)
            body = (f'{label(d)} amends this act. Its text is recorded in {amend_file(d)}; the act\'s own files are '
                    f'not rewritten until the next official consolidation (Nalunaarutit publishes no other text).\n\n'
                    f'Kilde: {d["url"]}\nText-applied: no\n')
        else:  # repeal
            for p in sorted(files[f]):
                ops.append((p, None))
            files[f] = set()
            subject = f'{f}: ophævet ved {label(d)}'
            author = ident(d)
            body = f'{label(d)}: "{e["line"]}"\n\nKilde: {d["url"]}\n'
        if not ops:
            continue
        counts[e['kind']] += 1
        new_done.append(f"{e['kind']}|{e['folder']}|{d['url']}")
        msg = (f'{subject}\n\n{body}\nKind: {e["kind"]}\nIn-force: {e["day"]}\nIn-force-basis: {e["basis"]}\n'
               f'Enacted: {d["enacted"]}\nStatus: {d["status"] or "not stated"}\n')
        if e['day'] < '1970-01-01':
            msg += 'Git-date: 1970 placeholder (git cannot record dates before 1970; the day is In-force)\n'
        mb = msg.encode('utf-8')
        when = git_date(e['day'])
        buf += f'commit refs/heads/{branch}\nmark :{i}\n'.encode()
        buf += f'author {author[0]} <{author[1]}> {when}\ncommitter {COMMITTER[0]} <{COMMITTER[1]}> {when}\n'.encode('utf-8')
        buf += f'data {len(mb)}\n'.encode() + mb
        if prev:
            buf += f'from {prev}\n'.encode()
            prev = None
        for p, v in ops:
            if v is None:
                buf += f'D {p}\n'.encode('utf-8')
            else:
                data = v.encode('utf-8')
                buf += f'M 100644 inline {p}\ndata {len(data)}\n'.encode('utf-8') + data + b'\n'
        buf += b'\n'
    out.write_bytes(bytes(buf))
    (WORK / 'done.pending.json').write_text(json.dumps(sorted(done | set(new_done)), ensure_ascii=False), encoding='utf-8')
    return {'events': len(ev), 'counts': dict(counts), 'split': dict(split_stats)}


def main():
    cmd = sys.argv[1]
    plan = make_plan()
    g = plan['groups']
    rep = {
        'docs': len(plan['docs']), 'groups': len(g),
        'groups_gl': sum(1 for f in g if not f.startswith(('rigslovgivning/', 'international/'))),
        'with_consolidations': sum(1 for x in g.values() if x['versions']),
        'amendments_linked': sum(len(x['amendments']) for x in g.values()),
        'unresolved_cons': len(plan['unresolved_cons']), 'unresolved_amends': len(plan['unresolved_amends']),
        'repeals': len(plan['repeals']), 'held': plan['held'], 'excluded': len(plan['excluded']),
        'families': Counter(d['family'] for d in plan['docs']),
    }
    (WORK / 'excluded.json').write_text(json.dumps(plan['excluded'], ensure_ascii=False, indent=1), encoding='utf-8')
    (WORK / 'held.json').write_text(json.dumps(plan['held'], ensure_ascii=False, indent=1), encoding='utf-8')
    rows = []
    for f, x in sorted(g.items()):
        d = x['base'] or x['versions'][0]
        rows.append({'folder': f, 'title': d['title'], 'label': label(d) if x['base'] else (x.get('cited_base') or label(d)),
                     'status': (x['versions'][-1]['status'] if x['versions'] else d['status']),
                     'versions': (1 if x['base'] else 0) + len(x['versions']), 'amendments': len(x['amendments']),
                     'source': d['url']})
    (WORK / 'acts.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    if cmd == 'plan':
        print(json.dumps({k: (v if k != 'held' else len(v)) for k, v in rep.items()}, ensure_ascii=False, indent=1))
        return
    part, branch, start = sys.argv[2], sys.argv[3], sys.argv[4]
    res = stream(plan, part, branch, start, WORK / f'stream-{part}.fi')
    print(json.dumps(res))


if __name__ == '__main__':
    main()

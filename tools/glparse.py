"""Reads Nalunaarutit's document pages into provisions, and reads amending acts for what they amend and when."""
from __future__ import annotations

import re

from lxml import html as lhtml

WS = re.compile('[\\s\u200b\u00ad\ufeff]+')
SECT = '\u00a7'
QUOTES = '”“»«"'
LBK_PREFIX = re.compile(r'^Selvstyrets\s+lovbekendtgørelse\s+af\s+', re.I)
MONTHS = {'januar': 1, 'februar': 2, 'marts': 3, 'april': 4, 'maj': 5, 'juni': 6, 'juli': 7, 'august': 8,
          'september': 9, 'oktober': 10, 'november': 11, 'december': 12}
DAY = re.compile(r'(\d{1,2})\.?\s*(' + '|'.join(MONTHS) + r')\s+(\d{4})', re.I)
KINDS = r'(Inatsisartutlov|Landstingslov|Landstingsforordning|Inatsisartutforordning)'
ACTREF = re.compile(KINDS + r'\s+nr\.?\s*(\d+)\.?\s*(?:,|af)?\s*(\d{1,2})\.?\s*(' + '|'.join(MONTHS) + r')\s+(\d{4})', re.I)
ROMAN = re.compile(r'\[([ivxl]+)\]')
ARTICLE = re.compile(r'^' + SECT + r'\s*(\d+)\s*\.?$')
SECTION = re.compile(r'^' + SECT + r'\s*(\d+)\s*([a-zA-Z]?)\s*\.\s*(.*)$', re.S)
SIGNATURE = re.compile(r'^(Grønlands (?:Selvstyre|Hjemmestyre)|Departementet\b.*|Formandens Departement\b.*),?\s+den\s+\d', re.I)
SEPARATOR = re.compile(r'^_{8,}$')
IKRAFT_LINE = re.compile(r'indeholder følgende ikrafttrædelsesbestemmelse', re.I)
NOTE = re.compile(r'^\[[ivxl]+\]\s+Lovændringen', re.I)


def clean(s: str) -> str:
    return WS.sub(' ', s).strip()


def danish_day(s: str) -> str | None:
    m = DAY.search(s)
    return f'{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}' if m else None


def long_day(day: str) -> str:
    y, mo, d = day.split('-')
    return f'{int(d)}. {list(MONTHS)[int(mo) - 1]} {y}'


def roman_int(s: str) -> int:
    vals = {'i': 1, 'v': 5, 'x': 10, 'l': 50}
    total, prev = 0, 0
    for ch in reversed(s.lower()):
        v = vals[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


# ---------------------------------------------------------------- the page

def page(raw_html: str) -> dict:
    """A document page: its header (kind, number, site date, status), title, relations (sidebar links) and body lines."""
    doc = lhtml.fromstring(raw_html)
    main = doc.get_element_by_id('main')
    rt = [d for d in main.iter('div') if 'richtext' in (d.get('class') or '')][0]
    title = ''
    for h in main.iter('h1', 'h2', 'h3'):
        title = clean(h.text_content())
        break
    head = []
    for e in main.iter():
        if e is rt:
            break
        if e.tag in ('p', 'h1', 'span', 'div', 'a', 'button') and e.text and e.text.strip():
            head.append(clean(e.text))
    kind = head[0] if head else ''
    number = next((int(h[4:]) for h in head if h.startswith('Nr. ')), None)
    site_day = next((danish_day(h) for h in head if danish_day(h)), None)
    status = next((h for h in head if h in ('Gældende', 'Ophævet', 'Vedtaget', 'Historisk')), '')
    rels = []
    for sd in doc.iter('div'):
        if not (sd.get('class') or '').startswith('col-span-1 xl:col-span-4'):
            continue
        for a in sd.iter('a'):
            href = a.get('href') or ''
            if '/Groenlandsk-lovgivning/' in href:
                rels.append((href.split('?')[0], clean(a.text_content())))
    return {'title': title, 'kind': kind, 'number': number, 'site_day': site_day, 'status': status, 'rels': rels,
            'lines': lines_of(rt)}


def lines_of(rt) -> list[tuple[str, str]]:
    """The body as (flags, text) lines: one per block element or <br>-separated run, in document order. Flags: C centred,
    B bold, I italic (of the enclosing element)."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush(flags):
        t = clean(''.join(buf))
        if t:
            out.append((flags, t))
        buf.clear()

    def walk(e, flags):
        if not isinstance(e.tag, str):
            if e.tail:
                buf.append(e.tail)
            return
        block = e.tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr', 'table', 'ul', 'ol', 'hr')
        st = (e.get('style') or '').replace(' ', '')
        f = flags
        if 'text-align:center' in st:
            f += 'C'
        if e.tag == 'strong':
            f += 'B'
        if e.tag == 'em':
            f += 'I'
        if block:
            flush(flags)
        if e.tag == 'br':
            flush(flags)
        else:
            if e.text:
                buf.append(e.text)
            for c in e:
                walk(c, f)
        if block:
            flush(f)
        if e.tail:
            buf.append(e.tail)
    walk(rt, '')
    flush('')
    return out


# ---------------------------------------------------------------- units of one version

def sec_key(num: str, suf: str) -> str:
    return f'par-{int(num):03d}{suf.lower()}'


def act_title(title: str) -> str:
    return LBK_PREFIX.sub('', title)


def read_units(pg: dict) -> dict:
    """One version as units in order: 'titel' (the act's title), 'indledning' (opening words), each provision (with the
    headings that begin with it), 'ikraft' (the commencement clauses of the amending acts a consolidation appends), 'slut'
    (signatures) and 'noter' (endnotes). Each unit has its lines and its text."""
    units: dict[str, dict] = {}
    order: list[str] = []
    pending: list[str] = []
    cur: dict | None = None
    state = 'open'
    lines = pg['lines']

    def unit(key, label, kind_):
        if key in units:
            raise SystemExit(f'duplicate unit {key}')
        u = {'key': key, 'label': label, 'kind': kind_, 'lines': []}
        units[key] = u
        order.append(key)
        return u

    unit('titel', 'Titel', 'titel')['lines'] = [act_title(pg['title'])]
    for i, (flags, text) in enumerate(lines):
        nxt = lines[i + 1][1] if i + 1 < len(lines) else ''
        if state in ('open', 'body'):
            if SEPARATOR.match(text) or IKRAFT_LINE.search(text) or (ACTREF.match(text) and IKRAFT_LINE.search(nxt)):
                state = 'ikraft'
                cur = unit('ikraft', 'Ikrafttrædelsesbestemmelser', 'ikraft')
                cur['lines'] += [f'## {h}' for h in pending]
                pending = []
            elif SIGNATURE.match(text):
                state = 'slut'
                cur = unit('slut', 'Slutning', 'slut')
                cur['lines'] += [f'## {h}' for h in pending]
                pending = []
        if state == 'ikraft' and 'C' in flags and not ARTICLE.match(text):
            state = 'slut'
            cur = unit('slut', 'Slutning', 'slut')
        if state in ('slut', 'ikraft') and NOTE.match(text):
            state = 'noter'
            cur = unit('noter', 'Noter', 'noter')
        if state in ('ikraft', 'slut', 'noter'):
            cur['lines'].append(text)
            continue
        m = SECTION.match(text)
        if m and not text.startswith(SECT + SECT):
            key = sec_key(m.group(1), m.group(2))
            label = f'{SECT} {int(m.group(1))}{(" " + m.group(2).lower()) if m.group(2) else ""}'
            if key in units:
                key += '-dup'
            cur = unit(key, label, 'paragraf')
            cur['lines'] = [f'## {h}' for h in pending] + [text]
            pending = []
            state = 'body'
            continue
        if 'C' in flags or re.fullmatch(r'(Kapitel|Afsnit)\s+\S+', text):
            pending.append(text)
            continue
        if state == 'open':
            if 'indledning' not in units:
                unit('indledning', 'Indledning', 'indledning')
            units['indledning']['lines'] += [f'## {h}' for h in pending] + [text]
            pending = []
        else:
            if pending:
                cur['lines'] += [f'## {h}' for h in pending]
                pending = []
            cur['lines'].append(text)
    if pending and cur is not None:
        cur['lines'] += [f'## {h}' for h in pending]
    for k in order:
        units[k]['text'] = '\n\n'.join(units[k]['lines']) + '\n'
    return {'units': units, 'order': order}


def unit_order(key: str) -> tuple:
    if key == 'titel':
        return (0, 0, '', '')
    if key == 'indledning':
        return (0, 1, '', '')
    m = re.fullmatch(r'par-(\d+)([a-z]*)(.*)', key)
    if m:
        return (1, int(m.group(1)), f'{len(m.group(2)):02d}{m.group(2)}', m.group(3))
    return ({'ikraft': 2, 'slut': 3, 'noter': 4}.get(key, 5), 0, key, '')


# ---------------------------------------------------------------- what a consolidation says

def preamble_acts(indledning: str) -> list[tuple[str, int, int, str]]:
    """The acts the opening words say are incorporated: (kind, number, year, day) in the order named."""
    out = []
    for line in indledning.split('\n\n'):
        if not line.startswith(('Herved bekendtg', 'Hermed bekendtg')):
            continue
        tail = re.split(r'med de ændringer,?\s+der følger af', line, 1)
        if len(tail) < 2:
            continue
        for kind, num, d, mon, y in ACTREF.findall(tail[1]):
            out.append((kind.lower(), int(num), int(y), f'{int(y):04d}-{MONTHS[mon.lower()]:02d}-{int(d):02d}'))
    return out


def note_map(units: dict) -> dict[int, set[str]]:
    """Endnote number -> the provision keys it names ('[i] Lovændringen vedrører titel, § 1, stk. 2 ...')."""
    out: dict[int, set[str]] = {}
    for line in (units.get('noter') or {}).get('lines', []):
        m = re.match(r'^\[([ivxl]+)\]\s*(.*)$', line, re.I)
        if m:
            keys = sections_in(m.group(2))
            if re.search(r'\btitel\b', m.group(2), re.I):
                keys.add('titel')
            out[roman_int(m.group(1))] = keys
    return out


def ikraft_map(units: dict) -> dict[int, tuple[tuple[str, int, int, str] | None, list[str]]]:
    """Endnote number -> (the act named with it in the appended commencement section, its quoted commencement lines)."""
    out: dict[int, tuple] = {}
    lines = (units.get('ikraft') or {}).get('lines', [])
    cur = None
    prev_ref = None
    for line in lines:
        m = ROMAN.search(line)
        ref = ACTREF.search(line)
        if m and IKRAFT_LINE.search(line):
            r = ref or prev_ref
            act = (r.group(1).lower(), int(r.group(2)), int(r.group(5)),
                   f'{int(r.group(5)):04d}-{MONTHS[r.group(4).lower()]:02d}-{int(r.group(3)):02d}') if r else None
            cur = roman_int(m.group(1))
            out[cur] = (act, [])
            prev_ref = None
            continue
        if ref and not m:
            prev_ref = ref
        if cur is not None and not SEPARATOR.match(line) and not ARTICLE.match(line):
            if ACTREF.match(line) and not re.search(r'træder i kraft|virkning', line):
                continue
            out[cur][1].append(line)
    return out


# ---------------------------------------------------------------- amending acts

NUM = r'\d+\s*(?:[a-zA-Z](?![a-zA-Z]))?(?:\s*[-–]\s*\d*\s*(?:[a-zA-Z](?![a-zA-Z]))?)?'
CONT = r'\d+(?![\d.])\s*(?:[a-zA-Z](?![a-zA-Z]))?(?:\s*[-–]\s*\d*\s*(?:[a-zA-Z](?![a-zA-Z]))?)?'
SECS = re.compile(SECT + SECT + r'?\s*(' + NUM + r'(?:\s*(?:,|og|samt)\s*' + CONT + r')*)')
ONE = re.compile(r'(\d+)\s*([a-zA-Z](?![a-zA-Z]))?(?:\s*[-–]\s*(\d*)\s*([a-zA-Z](?![a-zA-Z]))?)?')


def sections_in(lead: str) -> set[str]:
    """Provision keys a clause names: '§ 5', '§§ 5 og 6', '§§ 5-7', '§ 5 a', '§§ 26 a – 26 q'."""
    keys: set[str] = set()
    for m in SECS.finditer(lead):
        for a, s1, b, s2 in ONE.findall(m.group(1)):
            s1, s2 = s1 or '', s2 or ''
            if b and not s2:
                for n in range(int(a), int(b) + 1):
                    keys.add(sec_key(str(n), ''))
            elif b and s2 and s1 and a == b:
                for c in range(ord(s1.lower()), ord(s2.lower()) + 1):
                    keys.add(sec_key(a, chr(c)))
            elif s1 and s2 and not b:
                for c in range(ord(s1.lower()), ord(s2.lower()) + 1):
                    keys.add(sec_key(a, chr(c)))
            else:
                keys.add(sec_key(a, s1))
    return keys


ITEM = re.compile(r'^(\d+)\.\s+(.*)$', re.S)
LEAD_STOP = re.compile('[' + QUOTES + r']|\b(?:affattes|ophæves|udgår|indsættes|ændres|bliver|erstattes|tilføjes)\b')
QUOTED_SEC = re.compile('[' + QUOTES + r']\s*(' + SECT + r'\s*\d+\s*[a-zA-Z]?\s*\.)')
NEW_SEC = re.compile(r'^[' + QUOTES + r']?\s*(' + SECT + r'\s*\d+\s*[a-zA-Z]?\s*\.)')
GLOBAL = re.compile(r'\b(?:Overalt i loven|I hele loven|Overalt i lovens tekst)\b', re.I)
TITLE = re.compile(r'\b(?:Lovens|Landstingslovens|Inatsisartutlovens|Forordningens)\s+titel\b', re.I)


def articles(lines: list[tuple[str, str]]) -> dict[int, list[str]]:
    """An act's articles: number -> its text lines (the article line first). An article of an amending act is a line that
    is only '§ 1' (centred or not)."""
    out: dict[int, list[str]] = {}
    cur = None
    for flags, text in lines:
        m = ARTICLE.match(text)
        if m:
            cur = int(m.group(1))
            if cur in out:
                cur = None
                continue
            out[cur] = [text]
        elif cur is not None:
            out[cur].append(text)
    return out


def items_of(article: list[str]) -> dict[int, set[str]]:
    """The numbered items of an amending article ('1. I § 5, stk. 2, ændres ...') and the provisions each names: those
    in the lead clause before the new wording, and those the new wording opens with ('”§ 5 a. ...'). An article with a
    single unnumbered change counts as item 1."""
    out: dict[int, set[str]] = {}
    cur = None
    body_lines = article[1:]
    if not any(ITEM.match(l) for l in body_lines):
        body_lines = [l for l in body_lines if not re.search(r'foretages følgende ændring', l)]
        body_lines = ['1. ' + l for l in body_lines[:1]] + body_lines[1:]
    for line in body_lines:
        m = ITEM.match(line)
        if m:
            cur = int(m.group(1))
            body = m.group(2)
            lead = LEAD_STOP.split(body, 1)[0]
            out.setdefault(cur, set()).update(sections_in(lead))
            if GLOBAL.search(lead):
                out[cur].add('*')
            if TITLE.search(lead):
                out[cur].add('titel')
            for q in QUOTED_SEC.findall(body):
                out[cur] |= sections_in(q)
        elif cur is not None:
            for q in QUOTED_SEC.findall(line) + NEW_SEC.findall(line):
                out[cur] |= sections_in(q)
    return out


COMMENCE = re.compile(r'^(.*?)\s*,?\s*træder\s+i\s+kraft\s*(.*)$', re.I | re.S)
APPLIES = re.compile(r'har\s+virkning\s+(?:fra|for)', re.I)


def commencement(arts: dict[int, list[str]], lines: list[tuple[str, str]] | None = None) -> tuple[str | None, str]:
    """The day the act took effect, read from its own sentence ('Inatsisartutloven træder i kraft den 1. januar 2019',
    'Landstingsloven træder i kraft den 1. april 1993', '§ 29. Inatsisartutloven træder i kraft den 1. august 2010')."""
    texts = [l for n in sorted(arts) for l in arts[n]] if arts else [t for _, t in (lines or [])]
    for line in texts:
        if line[:1] in QUOTES:
            continue
        for sent in re.split(r'(?<=[a-zæøå0-9])\.\s+(?=[A-ZÆØÅ' + SECT + r'])', line):
            sent = re.sub(r'^(' + SECT + r'\s*\d+\.\s*)?(Stk\.\s*\d+\s*\.?\s*)?', '', sent.strip())
            m = COMMENCE.match(sent)
            if not m:
                continue
            scope = m.group(1).strip(' ,')
            if re.fullmatch(r'(Loven|Denne lov|Inatsisartutloven|Landstingsloven|Forordningen|Landstingsforordningen|Inatsisartutforordningen)',
                            scope, re.I):
                return danish_day(m.group(2)), sent
    return None, ''


def applies_sentences(arts: dict[int, list[str]]) -> list[str]:
    """Sentences giving a part of the act effect from another day ('§ 1, nr. 1-12, har virkning fra 1. januar 2024')."""
    out = []
    for n in sorted(arts):
        for line in arts[n]:
            if line[:1] in QUOTES:
                continue
            for sent in re.split(r'(?<=[a-zæøå0-9])\.\s+(?=[A-ZÆØÅ' + SECT + r'])', line):
                if APPLIES.search(sent) and danish_day(sent):
                    out.append(re.sub(r'^(Stk\.\s*\d+\s*\.?\s*)', '', sent.strip()))
    return out

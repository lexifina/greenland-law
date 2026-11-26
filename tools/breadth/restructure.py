"""Pure-rename commit: type/year folders. Writes work/paths.json (old -> new) and a fast-import stream with R lines."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r'C:\Users\alany\Documents\greenland-law')
WORK = Path(r'C:\Users\alany\Documents\greenland-work')


def git(*a):
    return subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True, encoding='utf-8', check=True).stdout


status = {r['folder']: r['status'] for r in json.loads((WORK / 'acts.json').read_text(encoding='utf-8'))}
GL_TYPES = {'inatsisartutlov': 'inatsisartutlove', 'landstingslov': 'landstingslove', 'lov': 'inatsisartutlove',
            'landstingsforordning': 'landstingsforordninger', 'inatsisartutforordning': 'inatsisartutforordninger',
            'bekendtgoerelse': 'bekendtgoerelser', 'vedtaegt': 'vedtaegter', 'regulativ': 'regulativer',
            'paabud': 'paabud', 'landsraadsvedtaegt': 'landsraadsvedtaegter', 'forretningsorden': 'forretningsordener',
            'lovbekendtgoerelse': 'lovbekendtgoerelser'}
RIGS_TYPES = {'lov': 'love', 'anordning': 'anordninger', 'bekendtgoerelse': 'bekendtgoerelser',
              'lovbekendtgoerelse': 'lovbekendtgoerelser', 'forretningsorden': 'forretningsordener'}
GRUNDLAG = {'rigslovgivning/lov-2009-473', 'rigslovgivning/lov-1978-577'}
FIXED = {'kirken': 'inatsisartutlove/2010/kirken', 'havneafgift': 'landstingslove/1992/havneafgift',
         'love.csv': 'data/love.csv', 'acts.csv': 'data/acts.csv', 'held.csv': 'data/held.csv',
         'visualisations': 'data/visualisations', 'vulnerabilities': 'data/vulnerabilities'}
KEEP = {'README.md', 'README.en.md', 'LICENSE', 'REPRODUCE.md', 'corpus.json', 'data', 'tools'}


def place(old: str) -> str:
    if old in FIXED:
        return FIXED[old]
    base = old.rsplit('/', 1)[-1]
    word = re.match(r'([a-z]+)-', base).group(1)
    year = re.search(r'(\d{4})', base).group(1)
    gone = status.get(old) == 'Ophævet'
    sub = f'ophaevede/{year}' if gone else year
    if old in GRUNDLAG:
        return f'grundlag/ophaevede/{base}' if gone else f'grundlag/{base}'
    if old.startswith('rigslovgivning/'):
        return f'rigslovgivning/{RIGS_TYPES[word]}/{sub}/{base}'
    if old.startswith('international/'):
        return f'international/{sub}/{base}'
    return f'{GL_TYPES[word]}/{sub}/{base}'


def main():
    head = git('rev-parse', 'HEAD').strip()
    root = [x for x in git('ls-tree', '--name-only', 'HEAD').split('\n') if x]
    olds = []
    for x in root:
        if x in KEEP:
            continue
        if x in ('rigslovgivning', 'international'):
            olds += [f'{x}/{y}' for y in git('ls-tree', '--name-only', f'HEAD:{x}').split('\n') if y]
        else:
            olds.append(x)
    mapping = {o: place(o) for o in olds}
    assert len(set(mapping.values())) == len(mapping), 'collision'
    counts = {}
    for n in mapping.values():
        parent = n.rsplit('/', 1)[0]
        counts[parent] = counts.get(parent, 0) + 1
    assert max(counts.values()) <= 1000, max(counts.items(), key=lambda kv: kv[1])
    (WORK / 'paths.json').write_text(json.dumps(dict(sorted(mapping.items())), ensure_ascii=False, indent=1) + '\n',
                                     encoding='utf-8', newline='\n')
    msg = ('Folders by type and year: grundlag/, inatsisartutlove/<år>/, landstingslove/<år>/, landstingsforordninger/<år>/, '
           'bekendtgoerelser/<år>/, rigslovgivning/<type>/<år>/, international/<år>/, repealed texts in ophaevede/ inside '
           'each type; tables and placeholders under data/\n\nRenames only: no file content changes. The old and new '
           'paths are listed in data/paths.json (next commit).\n\nKind: restructure\n').encode('utf-8')
    now = int(time.time())
    s = bytearray(f'commit refs/heads/main\ncommitter Lexifina <greenland-law@lexifina.com> {now} +0000\n'.encode())
    s = bytearray(f'commit refs/heads/main\nauthor Lexifina <greenland-law@lexifina.com> {now} +0000\n'
                  f'committer Lexifina <greenland-law@lexifina.com> {now} +0000\n'.encode())
    s += f'data {len(msg)}\n'.encode() + msg + f'from {head}\n'.encode()
    for o, n in sorted(mapping.items()):
        s += f'R "{o}" "{n}"\n'.encode('utf-8')
    s += b'\n'
    (WORK / 'rename.fi').write_bytes(bytes(s))
    print(len(mapping), sorted(counts.items(), key=lambda kv: -kv[1])[:5])
    tops = sorted({n.split('/')[0] for n in mapping.values()})
    print(tops)


main()

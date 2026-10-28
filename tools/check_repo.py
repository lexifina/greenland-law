"""Checks the git repository against the official text: every version of every act on Nalunaarutit, read back from git
with tools/paa_dato.py on the day it took effect, must equal that version's text.

    python -X utf8 scripts/greenland-law/check_repo.py [--repo ../greenland-law] [--no-record]

Two checks per version, from the cached Nalunaarutit pages (no network):
1. File by file: the act's files in git on that day are exactly the files the build's parser makes from that version's
   HTML (same set of files, same bytes).
2. Word for word: the whole act printed by paa_dato.py, with its markdown marks removed, has the same words in the same
   order as the whole official page, read independently of the parser (its title and every text node of its text body).
The result is written to verification.json next to this script (unless --no-record), for REPRODUCE.md.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from lxml import html as lhtml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

TOKEN = re.compile(r'\w+|[^\w\s]')


def official_words(raw_html: str) -> list[str]:
    """All words of the page that are the act: its title (the heading above the text) and every text node of the text body
    (the 'richtext' block), read with lxml directly, not with the build's parser."""
    doc = lhtml.fromstring(raw_html)
    main = doc.get_element_by_id('main')
    title = next(iter(main.iter('h1', 'h2', 'h3'))).text_content()
    title = re.sub(r'^\s*Selvstyrets\s+lovbekendtgørelse\s+af\s+', '', title)
    rt = [d for d in main.iter('div') if 'richtext' in (d.get('class') or '')][0]

    def text(e) -> str:
        if not isinstance(e.tag, str):
            return e.tail or ''
        gap = ' ' if e.tag in ('div', 'br', 'p', 'td', 'th', 'tr', 'table', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5',
                               'h6', 'hr') else ''
        return gap + (e.text or '') + ''.join(text(c) for c in e) + gap + (e.tail or '')
    body = title + ' ' + text(rt)[:-len(rt.tail or '') or None]
    return TOKEN.findall(re.sub('[\u00ad\u200b\ufeff]', '', body))


def repo_words(text: str) -> list[str]:
    lines = []
    for l in text.split('\n'):
        l = re.sub(r'^\s*(#+ |- )', '', l)
        lines.append(l.replace(' | ', ' '))   # the separator between the cells of a table row
    return TOKEN.findall(' '.join(lines))


def tool(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, 'tools/paa_dato.py', *args], cwd=repo, capture_output=True, text=True,
                          encoding='utf-8')


def files_at(repo: str, commit: str, slug: str) -> dict[str, str]:
    """The act's files at a commit, read with one ls-tree and one cat-file --batch (not one git show per file)."""
    out = subprocess.run(['git', 'ls-tree', '-r', commit, f'{slug}/'], cwd=repo, capture_output=True,
                         text=True, encoding='utf-8').stdout.split('\n')
    blobs = []
    for line in out:
        if not line:
            continue
        info, f = line.split('\t', 1)
        if f.endswith('.md') and not f.endswith('/README.md'):
            blobs.append((f[len(slug) + 1:], info.split()[2]))
    if not blobs:
        return {}
    data = subprocess.run(['git', 'cat-file', '--batch'], cwd=repo, input=''.join(f'{sha}\n' for _, sha in blobs).encode(),
                          capture_output=True).stdout
    res, pos = {}, 0
    for name, _ in blobs:
        nl = data.index(b'\n', pos)
        size = int(data[pos:nl].split()[2])
        res[name] = data[nl + 1:nl + 1 + size].decode('utf-8')
        pos = nl + 1 + size + 1
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=str(HERE.parent if (HERE.parent / '.git').exists()
                                                     else build.ROOT.parent / 'greenland-law'))
    ap.add_argument('--no-record', action='store_true')
    args = ap.parse_args()
    versions = files = bad = words = wbad = 0
    nwords = 0
    per_act = {}
    paths = build.sitemap(True)
    for act in build.ACTS:
        for v in build.build_act(act, True, paths)['versions']:
            day = v['from']
            expected = {f'{k}.md': u['text'] for k, u in v['units'].items()}
            commit = subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, "tools"); import paa_dato; '
                                     f'print(paa_dato.commit_on("{day}", "{act["slug"]}"))'],
                                    cwd=args.repo, capture_output=True, text=True).stdout.strip()
            got = files_at(args.repo, commit, act['slug']) if commit else {}
            versions += 1
            per_act[act['slug']] = per_act.get(act['slug'], 0) + 1
            files += len(expected)
            if got != expected:
                bad += 1
                diff = sorted(set(got) ^ set(expected)) or [k for k in expected if got.get(k) != expected[k]]
                print(f'MISMATCH {act["slug"]} {day}: {diff[:5]}')
            whole = tool(args.repo, day, act['slug'])
            words += 1
            ow, rw = official_words(build.fetch(v['key'] + build.LANG, offline=True).decode('utf-8')), repo_words(whole.stdout)
            nwords += len(ow)
            if whole.returncode or ow != rw:
                wbad += 1
                i = next((i for i, (a, b) in enumerate(zip(ow, rw)) if a != b), min(len(ow), len(rw)))
                print(f'WORDS {act["slug"]} {day}: official {len(ow)} vs repo {len(rw)} words; first difference at '
                      f'{i}: {" ".join(ow[max(0, i - 5):i + 5])!r} / {" ".join(rw[max(0, i - 5):i + 5])!r}')
    print(f'{versions} versions checked ({files} files), {bad} mismatches; {words} versions word for word '
          f'({nwords} words), {wbad} mismatches')
    print('per act:', per_act)
    if not args.no_record:
        p = HERE / 'verification.json'
        rec = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        rec['check'] = {'versions': versions, 'files': files, 'mismatches': bad, 'wordcheck': words,
                        'words': nwords, 'word_mismatches': wbad, 'per_act': per_act}
        p.write_text(json.dumps(rec, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    raise SystemExit(1 if bad or wbad else 0)


if __name__ == '__main__':
    main()

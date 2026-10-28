"""Prints an act, or one provision of it, as it stood on a given day, from this repository's history.

    python tools/paa_dato.py 2010-01-01 havneafgift 3      # § 3 of the port dues act on 1 January 2010
    python tools/paa_dato.py 2020-01-01 kirken             # the whole church act on 1 January 2020
    python tools/paa_dato.py 2020-01-01 kirken 26a         # § 26 a
    python tools/paa_dato.py 2026-02-01 havneafgift titel  # the act's title

Each commit carries the day its change took effect in an `In-force:` trailer (git cannot store dates before 1970, so
the trailer, not the commit date, is the source of truth). The text in force on a day is the last commit on or before
it. Standard library only.
"""
import datetime as dt
import re
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def order(path: str) -> tuple:
    """The order of the act's files: title, opening words, provisions by number, commencement clauses, signatures, notes."""
    name = path.split('/', 1)[1][:-3]
    if name == 'titel':
        return (0, 0, '', '')
    if name == 'indledning':
        return (0, 1, '', '')
    m = re.fullmatch(r'par-(\d+)([a-z]*)(.*)', name)
    if m:
        return (1, int(m.group(1)), f'{len(m.group(2)):02d}{m.group(2)}', m.group(3))
    return ({'ikraft': 2, 'slut': 3, 'noter': 4}.get(name, 5), 0, name, '')


def file_for(act: str, key: str) -> str:
    """'7' -> par-007.md, '26a' -> par-026a.md; anything else is a file name (titel, indledning, ikraft, slut, noter)."""
    m = re.fullmatch(r'(\d+)\s*([a-z]*)', key)
    if m:
        return f'par-{int(m.group(1)):03d}{m.group(2)}.md'
    return key if key.endswith('.md') else f'{key}.md'


def commit_on(day: str, act: str) -> str:
    branch = 'main'
    out = git('log', '--format=%H%x09%(trailers:key=In-force,valueonly,separator=)', branch, '--', act)
    for line in out.splitlines():
        h, _, d = line.partition('\t')
        if d.strip() and d.strip() <= day:
            return h
    return ''


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    day, act = sys.argv[1], sys.argv[2]
    dt.date.fromisoformat(day)
    commit = commit_on(day, act)
    if not commit:
        sys.exit(f'{act} is not in the record on {day}.')
    if len(sys.argv) > 3:
        name = file_for(act, sys.argv[3])
        try:
            sys.stdout.write(git('show', f'{commit}:{act}/{name}'))
        except subprocess.CalledProcessError:
            sys.exit(f'{act}/{name} was not in the text on {day}.')
        return
    files = [f for f in git('ls-tree', '-r', '--name-only', commit, f'{act}/').split('\n')
             if f.endswith('.md') and not f.endswith('/README.md')]
    for f in sorted(files, key=order):
        sys.stdout.write(git('show', f'{commit}:{f}') + '\n')


if __name__ == '__main__':
    main()

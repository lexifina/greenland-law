"""Writes data/versioner.json, corpus.json and REPRODUCE.md into the Greenlandic law repository, from the facts of the build
that made it. Called by build.py; kept apart so the record of how the repository was made reads as one document.

The results of the checks (check_repo.py, test_repo.py and the rebuild that compares hashes) are read from
verification.json next to this file, which check_repo.py, `test_repo.py --record` and `build.py --verify-rebuild` write.
They describe the build before the one that writes this file, from the same data; a rebuild with the same data and the
same verification.json gives the same hashes."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def last_day(built: list[dict], today: str) -> str:
    days = [b['versions'][0]['from'] for b in built] + [c['from'] for b in built for c in b['changes']]
    for b in built:
        for ch in b['changes']:
            days += [d for (_, d) in ch['groups']]
    return max(d for d in days if d <= today)


def write_manifest(repo: Path, built: list[dict], today: str):
    """Every source document the text comes from, with its sha256, so a rebuild can show it read the same bytes; and
    corpus.json, the corpus's self-description."""
    out = {'built': today, 'source': 'https://nalunaarutit.gl', 'acts': [{
        'label': b['label'], 'slug': b['act']['slug'], 'title': b['title'],
        'versions': [{'from': v['from'], 'document': v['doc']['label'], 'url': v['url'], 'sha256': v['sha256'],
                      'incorporated': [f'{k} nr. {n} ({y}), {d}' for k, n, y, d in v['incorporated']]} for v in b['versions']],
        'amending_acts': [{'document': d['label'], 'url': d['url'], 'sha256': d['sha256']}
                          for p, d in sorted(b['laws'].items(), key=lambda x: (x[1]['enacted'], x[1]['number'])) if p != b['key']],
    } for b in built]}
    (repo / 'data').mkdir(exist_ok=True)
    (repo / 'data' / 'versioner.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8',
                                                  newline='\n')
    corpus = {
        'corpus': 'gl/national/acts',
        'name': 'Greenlandic law: Inatsisartutlov om Kirken (nr. 9 af 19. maj 2010) and Landstingslov om havne- og '
                'krydstogtpassagerafgift (nr. 20 af 30. oktober 1992), with their consolidations and amending acts',
        'acts': [b['label'] for b in built],
        'history_from': min(b['versions'][0]['from'] for b in built),
        'built': today,
        'dates': {'commit': 'in-force', 'other_trailers': ['Enacted', 'Site-date', 'Signed'],
                  'time': '12:00 America/Nuuk (UTC-3, UTC-2 in summer time, until 25 March 2023; UTC-2 until 30 March '
                          '2024; since then UTC-2, UTC-1 in summer time)'},
        'scope': {
            'trailer': 'Applies',
            'when_absent': 'a commit without Applies: records no scope note; the absence is not a statement that the change reaches every case',
            'default_reach': {
                'rule': 'no retroactive criminal liability; no general bar elsewhere',
                'meaning': 'an act applies from the day it takes effect; an act may give itself effect from an earlier day '
                           '(an amending act says so: "har virkning fra ..."), except that no one is punished for an act that '
                           'was not punishable by law when it was done',
                'authority': 'Kriminallov for Grønland (lov nr. 306 af 30. april 2008) § 1 (the legality principle) and '
                             'Article 7 of the European Convention on Human Rights; Danmarks Riges Grundlov, which applies '
                             'in Greenland, contains no general rule on retroactive legislation. Not quoted here: the '
                             'wording was not read from an official source in this build',
                'decided_here': False,
            },
        },
        'tool': 'tools/paa_dato.py',
        'in_force_trailer': 'In-force',
        'record_to': last_day(built, today),
    }
    (repo / 'corpus.json').write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def write_reproduce(repo: Path, built: list[dict], log: list[dict], tags: dict, requests: list[dict], today: str):
    blob = subprocess.run(['git', 'hash-object', str(HERE / 'build.py')], capture_output=True, text=True).stdout.strip()
    pyv = subprocess.run(['python', '--version'], capture_output=True, text=True).stdout.strip()
    gitv = subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip()
    try:
        import lxml.etree
        lxmlv = '.'.join(str(x) for x in lxml.etree.LXML_VERSION[:3])
    except Exception:
        lxmlv = '?'
    ver = json.loads((HERE / 'verification.json').read_text(encoding='utf-8')) if (HERE / 'verification.json').exists() else {}
    n_req = len({r['url'] for r in requests})
    n_law = sum(1 for c in log if c['kind'] == 'law')
    n_empty = sum(1 for c in log if c['kind'] == 'law' and not c['units'])
    n_cand = sum(1 for c in log if c['kind'] == 'candidates')
    n_early = sum(1 for c in log if c['kind'] == 'early')
    n_cons = sum(1 for c in log if c['kind'] == 'consolidation')
    n_start = sum(1 for c in log if c['kind'] == 'start')
    n_clamped = sum(1 for c in log if c['clamped'])
    why: dict[str, int] = {}
    listed: dict[str, list[str]] = {}
    for b in built:
        for ch in b['changes']:
            for k in sorted(ch['why']):
                w = ch['why'][k]
                w2 = 'headings moved' if w.startswith('headings moved') else w.split('; day ')[0]
                why[w2] = why.get(w2, 0) + 1
                c = ch['cause'][k]
                group = ('candidates' if c == 'candidates' else 'unexplained' if c == 'unexplained' else
                         'early' if c.startswith('early:') else 'layout' if c == 'layout' else None)
                if group:
                    lab = (ch['cur']['units'].get(k) or ch['prev']['units'][k])['label']
                    listed.setdefault(group, []).append(f'{b["act"]["short"]} {lab}: committed {ch["when"][k]}, shown by the version of {ch["from"]}')
    n_changes = sum(why.values())
    rows = '\n'.join(
        f'| {b["label"]} | {b["title"]} | `{b["act"]["slug"]}/` | {len(b["versions"])} | '
        f'{b["versions"][0]["from"]} to {b["versions"][-1]["from"]} | {len(b["versions"][-1]["units"])} |' for b in built)
    chk, det, smoke = ver.get('check', {}), ver.get('rebuild', {}), ver.get('smoke', {})
    check_line = (f'`{chk["versions"]} versions checked ({chk["files"]} files), {chk["mismatches"]} mismatches; '
                  f'{chk["wordcheck"]} versions word for word ({chk["words"]} words) against the whole official text, '
                  f'{chk["word_mismatches"]} mismatches`' if chk else '(not yet run)')
    rebuild_line = (f'A second build from the same cache into an empty folder gave the same history: the last law commit '
                    f'was `{det["history_tip"]}` in both, and every one of the {det["commits"]} law commits and {det["tags"]} '
                    f'tags had the same hash.' if det.get('identical') else '(not yet run)')
    smoke_lines = ('\n'.join(f'   - {"pass" if r["ok"] else "FAIL"}: {r["test"]}: {r["detail"]}' for r in smoke['results'])
                   if smoke else '   (not yet run)')
    smoke_head = f'{smoke["passed"]} of {smoke["total"]} passed' if smoke else 'not yet run'

    def items(w):
        return '\n'.join(f'- {x}' for x in listed.get(w, [])) or '- none'

    text = f"""# How this history was made, and how to make it again

This file records exactly how the repository was built: the sources, the commands, the software, the decisions made
by hand, and what an AI model did and did not do. The build writes it, so it describes the build that made this
commit.

## Short version

```sh
git clone https://github.com/lexifina/greenland-law && cd greenland-law
pip install lxml
python -X utf8 tools/build.py --repo ../rebuilt --today {today}
git -C ../rebuilt rev-parse main        # the same hash as this repository's main
python -X utf8 tools/check_repo.py --repo ../rebuilt --no-record
python -X utf8 tools/test_repo.py --repo ../rebuilt
```

`tools/build.py` needs Python 3.12 or later with `lxml`, and git. It reads Nalunaarutit (or its own cache, `.cache/` next
to the script) and writes this repository into `--repo`. With the same Nalunaarutit pages and the same `--today` it gives
the same commits with the same hashes. `data/versioner.json` lists every page it read with the sha256 of the HTML, so a
rebuild can show it read the same bytes; Nalunaarutit may change its pages, and then the hashes change too.

## Sources and terms

All legal text and all information about consolidations and amending acts come from **Nalunaarutit**
(https://nalunaarutit.gl), Grønlands Selvstyres elektroniske lovsamling, the official electronic law collection of the
Government of Greenland. Nothing was typed in, summarised or rewritten. The build reads {n_req} pages:

| What | Where |
| --- | --- |
| The list of all pages | `https://nalunaarutit.gl/api/sitemap/sitemapxml` (the sitemap robots.txt names) |
| Each act, amending act and consolidation: title, number, day, status, text, related acts | `https://nalunaarutit.gl/Groenlandsk-lovgivning/<year>/<page>?sc_lang=da` (server-rendered HTML, Danish) |

| Act | Title | Folder | Versions | In force from | Files today |
| --- | --- | --- | ---: | --- | ---: |
{rows}

**Terms of use.** No terms of use and no reuse licence were found on Nalunaarutit: the page "Om Nalunaarutit.gl" describes
what the collection holds and gives a contact (nsninatsit@nanoq.gl), and `robots.txt` disallows only `/sitecore/`, names no
crawl delay and has no rule for AI agents. Whether Greenlandic acts are free of copyright as Danish acts are (ophavsretsloven
§ 9) has not been decided here, so **no reuse licence is claimed for the text and the repository stays private**. Requests
were made at most four at a time, with `Accept-Encoding: gzip` and the user agent `lexifina-watch/1.0
(+https://lexifina.com/watch; corpus@lexifina.com)`, each page once (a file cache). The data was retrieved on {today}.
Attribution: "Source: Nalunaarutit, Grønlands Selvstyre, https://nalunaarutit.gl". This repository is not endorsed by
Grønlands Selvstyre.

## The build, step by step

1. `python -X utf8 scripts/greenland-law/build.py --today {today}` in Lexifina's own repository fetched the pages into its
   cache and wrote this repository. `tools/build.py` here is the same file as `scripts/greenland-law/build.py` there (git
   blob `{blob}`), with `tools/glfetch.py`, `tools/glparse.py`, `tools/reproduce.py`, `tools/check_repo.py` and
   `tools/test_repo.py`. Every later build ran with `--offline`, from the cache.
2. `python -X utf8 scripts/greenland-law/check_repo.py` read every version of each act back from this repository with
   `tools/paa_dato.py`, on the day it took effect, and compared it file by file with the official text parsed afresh from
   the cached HTML; then it compared the whole act, word for word, with all the words of the official page (its title and
   its text body), read without the build's parser. Result: {check_line}.
3. `python -X utf8 scripts/greenland-law/test_repo.py --record` ran the functional smoke test against this repository
   ({smoke_head}):
{smoke_lines}
4. `python -X utf8 scripts/greenland-law/build.py --offline --verify-rebuild` built the repository a second time from the
   same cache into a temporary folder and compared the hashes. {rebuild_line}
5. The build was run once more to write these results into this file, and the final `main` was rebuilt again in a
   temporary folder and compared hash for hash before it was pushed.
6. `git push -f origin main --tags` published it to the private GitHub repository `lexifina/greenland-law`, replacing the
   placeholder (the first publication; later builds are appended, never forced).

It ran with {pyv}, lxml {lxmlv} and {gitv} on Windows 11. No network service other than Nalunaarutit is involved.

## How the text and the commits are derived

Everything below is done by `tools/build.py` and `tools/glparse.py`, deterministically.

- **Versions.** The act as passed, then each consolidation (Selvstyrets lovbekendtgørelse) on Nalunaarutit whose opening
  words ("Herved bekendtgøres ...") name the act by number and day, each from its own day (the day in its designation).
  The consolidations are found by reading every consolidation page in the sitemap.
- **Text.** Each act is a folder. Each provision (§) is one file named by its number: `par-005.md`, `par-026a.md`
  (§ 26 a). Headings (Kapitel, centred headings) that begin with a provision are `##` lines at the top of its file; each
  paragraph (stk.), list item and line break of the HTML is one line, separated by blank lines. `titel.md` is the act's
  title (for a consolidation, the title without "Selvstyrets lovbekendtgørelse af"), `indledning.md` the opening words
  (for a consolidation, the sentence naming the acts it incorporates), `ikraft.md` the commencement clauses of the amending
  acts that a consolidation quotes after the text, `slut.md` the place, day and signatures, `noter.md` the endnotes.
- **Normalised.** Only white space: runs of spaces, line breaks, no-break spaces, zero-width spaces, soft hyphens and
  byte-order marks become one space or nothing.
- **Changes.** Consecutive versions are compared file by file. {n_changes} changes of a file were found.
- **Cause.** A consolidation names in its opening words the amending acts it incorporates, quotes after the text the
  commencement clause of each, numbered [i], [ii] ..., and says in an endnote with the same number which provisions that act
  changed ("[i] Lovændringen vedrører § 3, stk. 1, nr. 3 og stk. 2"). The build also reads each amending act's own page:
  the article that amends this act, its numbered items ("1. I § 5, stk. 2, ændres ...") and the provisions each names or
  whose new wording it quotes. A changed file is credited to an act in this order:
  1. exactly one act names the provision, in the endnote or in its amending article
     ({why.get('named by the consolidation’s endnote or the amending article', 0)} file changes);
  2. an item that says "Overalt i loven", in exactly one act ({why.get('global replacement item of the amending article', 0)});
  3. the new wording is quoted word for word in exactly one act's text ({why.get('the new wording is quoted in the amending act', 0)});
  4. headings that only moved with a neighbouring provision an act changed ({why.get('headings moved', 0)});
  5. more than one act names (or quotes) it: credited to none, committed by the publisher with a `Candidate:` trailer per
     act ({why.get('named by the endnotes or amending articles of more than one act', 0) + why.get('global replacement items of more than one act', 0) + why.get('the new wording is quoted in more than one act', 0)});
  6. the provision changed only in its paragraph breaks or white space, no word: committed by the publisher, labelled
     `Layout-only:` ({why.get('only paragraph breaks or white space differ; no word changed', 0)});
  7. otherwise, and for the consolidation's own parts (opening words, quoted commencement clauses, signatures, notes): no
     act; committed by the publisher and labelled `Unexplained:` ({why.get('no endnote and no amending article of the consolidation names it', 0)}
     provisions, plus the editorial files of each consolidation, {why.get('editorial part of the consolidation (opening words, commencement clauses, signatures, notes)', 0)}).
- **Printed early.** A consolidation may print an act that takes effect after the consolidation's own day (Selvstyrets
  lovbekendtgørelse nr. 41 af 19. oktober 2026 prints Inatsisartutlov nr. 29 af 25. juni 2026, in force 1 January 2027).
  Such a change is never credited to the act: it is committed by the publisher on the consolidation's day, with a
  `Printed-early:` trailer naming the act and its day ({n_early} commit(s)).
- **Date.** The day a change took effect is read from the amending act's own commencement sentence ("Inatsisartutloven
  træder i kraft den 1. januar 2019"), quoted in the commit. Where it cannot be read, the consolidation's day is used
  (`Date-note: undated`); a day before the previous version's is clamped to it (`Date-note: late`). Where the consolidation
  quotes the clause with another day, the act's own text is used and the commit says so. Changes credited to several
  candidates take the latest of their days, at most the consolidation's day. The first version of an act takes the day of
  its own commencement sentence.
- **Commits.** One commit per amending act and in-force day ({n_law} law commits, of which {n_empty} change no words of
  that act: every act a consolidation incorporates is in the record), one for the first version of each act ({n_start}),
  {n_cand} for changes several acts could explain, {n_early} for changes printed early, and one per consolidation ({n_cons})
  holding its own parts and whatever nothing explains, in the order they took effect, then one for this documentation. The
  consolidation's commit is last on its day, so the repository on that day equals the official text.
  - The author is the amending act, `Inatsisartutlov nr. 2 af 29. november 2013`, at an address ending
    `@nalunaarutit.invalid` (`il-2013-2@nalunaarutit.invalid`; `ltl-` for a landstingslov). The first version of each act
    is credited to the act itself.
  - Commits by `Nalunaarutit (Grønlands Selvstyre)` are the publisher's own: a consolidation's own parts, layout-only and
    unexplained changes, changes with several candidate acts, and changes printed early.
  - Author and committer dates are noon in Nuuk on the day the change took effect, written into the code because the
    build machine has no time-zone database: UTC-3, or UTC-2 in European summer time (from the last Sunday in March to
    the last Sunday in October; September until 1995; none before 1980), until 25 March 2023; UTC-2 all year from
    26 March 2023 (Greenland moved its standard time and did not change back in October 2023); since 31 March 2024 UTC-2,
    or UTC-1 in European summer time. The committer is `Lexifina <greenland-law@lexifina.com>`. {n_clamped} commit(s) are
    before 1970.
  - Every commit carries `In-force:`, and the trailers `Evidence:`, `Kind:`, `Enacted:`, `Site-date:`, `Status:`,
    `Date-note:`, `Applies:`, `Affecting:`, `Candidate:`, `Printed-early:`, `Layout-only:`, `Unexplained:`, `Signed:`,
    `Source:` (the act on Nalunaarutit) and `Consolidated:` (the consolidation the text came from) where they apply.
  - Tags: each act's days (`havneafgift/2023-12-01`), each amending act (`il/2023-61`, `ltl/1994-11`, or one tag per day
    where it took effect on several days) and each consolidation (`lbk/2024-23`); {len(tags)} in all.
- **Documentation commit.** Dated {today}, the day the data was retrieved, not the day of the run, so a later rebuild of
  the same data gives the same hash.

Changes with several candidate acts (credited to none):

{items('candidates')}

Changes printed before the act takes effect:

{items('early')}

Changes of paragraph breaks alone:

{items('layout')}

Changes nothing explains:

{items('unexplained')}

## Decisions made by hand

1. **The acts.** Greenland's constitutional basis, the Self-Government Act (lov nr. 473 af 12. juni 2009), is a Danish act
   published on Retsinformation, not on Nalunaarutit, so it is left out. Of the {124} consolidations on Nalunaarutit (a
   survey of every Danish-language consolidation page), the two acts below have the clearest record:
   - Inatsisartutlov nr. 9 af 19. maj 2010 om Kirken: the act as passed and one consolidation (nr. 41 af 19. oktober 2026)
     incorporating three amending acts, one of them printed before it takes effect.
   - Landstingslov nr. 20 af 30. oktober 1992 om havneafgift (now havne- og krydstogtpassagerafgift): the act as passed and
     two consolidations (nr. 23 af 26. april 2024 and nr. 4 af 28. januar 2026), with twelve amending acts from 1993 to 2025.
     It is the only Self-Government act on the site with two consolidations.
2. **A consolidation is a snapshot, not a sequence.** Between two versions several acts take effect on different days;
   Nalunaarutit publishes no text for the days in between. Those days are reconstructed: each act's changes appear on its
   own in-force day, with the wording the next consolidation shows for the provisions the act names. Only the states on the
   days of the act as passed and of each consolidation are official texts.
3. **The consolidation's day is its in-force day**, the day in its designation.
4. **Danish only.** Nalunaarutit also publishes the acts in Greenlandic; the Danish text is used throughout.

## What an AI model did

This repository was built on {today} in **Claude Code**, Anthropic's coding tool, working from a brief by the user at
Lexifina: a private "git for law" repository for Greenland to the same standard as Lexifina's other corpora. One session
researched the source and the acts and wrote the first builder; it was stopped by a usage limit, and a second session, the
model **Claude Opus 5.5** (model id `claude-opus-5-5`), finished the builder, the checks and the documentation.

The models:

- **Researched the source:** Nalunaarutit's pages and sitemap, its robots.txt and the absence of terms of use.
- **Wrote all the code and text in this repository:** `tools/build.py`, `tools/glparse.py`, `tools/glfetch.py`,
  `tools/reproduce.py`, `tools/check_repo.py`, `tools/test_repo.py`, `tools/paa_dato.py`, the README, this file and the
  licence, and chose the design described in them.
- **Ran the commands above** and checked the results.

The models did **not**:

- **Write or edit any legal text.** Every word of every provision, every date and every act's title is copied by the script
  from Nalunaarutit; every in-force day is read by the script from the act's own sentence.
- **Take part in building the history.** No AI model is called when the history is built or checked.

The user decided what was in scope and decides whether the repository is ever made public. The work was not reviewed line
by line by a lawyer.

## Prior art

No public git history of Greenlandic law was found. Lexifina's other corpora, whose rules this one follows, are the model
(Denmark above all, whose acts and consolidations work the same way).
"""
    (repo / 'REPRODUCE.md').write_text(text, encoding='utf-8', newline='\n')

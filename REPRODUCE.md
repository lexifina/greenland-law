# How this history was made, and how to make it again

This file records exactly how the repository was built: the sources, the commands, the software, the decisions made
by hand, and what an AI model did and did not do. The build writes it, so it describes the build that made this
commit.

## Short version

```sh
git clone https://github.com/lexifina/greenland-law && cd greenland-law
pip install lxml
python -X utf8 tools/build.py --repo ../rebuilt --today 2026-10-28
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
Government of Greenland. Nothing was typed in, summarised or rewritten. The build reads 92 pages:

| What | Where |
| --- | --- |
| The list of all pages | `https://nalunaarutit.gl/api/sitemap/sitemapxml` (the sitemap robots.txt names) |
| Each act, amending act and consolidation: title, number, day, status, text, related acts | `https://nalunaarutit.gl/Groenlandsk-lovgivning/<year>/<page>?sc_lang=da` (server-rendered HTML, Danish) |

| Act | Title | Folder | Versions | In force from | Files today |
| --- | --- | --- | ---: | --- | ---: |
| Inatsisartutlov nr. 9 af 19. maj 2010 | Inatsisartutlov om Kirken | `kirken/` | 2 | 2010-08-01 to 2026-10-19 | 54 |
| Landstingslov nr. 20 af 30. oktober 1992 | Landstingslov om havneafgift | `havneafgift/` | 3 | 1993-01-01 to 2026-01-28 | 24 |

**Terms of use.** No terms of use and no reuse licence were found on Nalunaarutit: the page "Om Nalunaarutit.gl" describes
what the collection holds and gives a contact (nsninatsit@nanoq.gl), and `robots.txt` disallows only `/sitecore/`, names no
crawl delay and has no rule for AI agents. Whether Greenlandic acts are free of copyright as Danish acts are (ophavsretsloven
§ 9) has not been decided here, so **no reuse licence is claimed for the text and the repository stays private**. Requests
were made at most four at a time, with `Accept-Encoding: gzip` and the user agent `lexifina-watch/1.0
(+https://lexifina.com/watch; corpus@lexifina.com)`, each page once (a file cache). The data was retrieved on 2026-10-28.
Attribution: "Source: Nalunaarutit, Grønlands Selvstyre, https://nalunaarutit.gl". This repository is not endorsed by
Grønlands Selvstyre.

## The build, step by step

1. `python -X utf8 scripts/greenland-law/build.py --today 2026-10-28` in Lexifina's own repository fetched the pages into its
   cache and wrote this repository. `tools/build.py` here is the same file as `scripts/greenland-law/build.py` there (git
   blob `a806ee489d90aeb0b8031728f3a3065f3bb47f74`), with `tools/glfetch.py`, `tools/glparse.py`, `tools/reproduce.py`, `tools/check_repo.py` and
   `tools/test_repo.py`. Every later build ran with `--offline`, from the cache.
2. `python -X utf8 scripts/greenland-law/check_repo.py` read every version of each act back from this repository with
   `tools/paa_dato.py`, on the day it took effect, and compared it file by file with the official text parsed afresh from
   the cached HTML; then it compared the whole act, word for word, with all the words of the official page (its title and
   its text body), read without the build's parser. Result: `5 versions checked (153 files), 0 mismatches; 5 versions word for word (12159 words) against the whole official text, 0 mismatches`.
3. `python -X utf8 scripts/greenland-law/test_repo.py --record` ran the functional smoke test against this repository
   (6 of 6 passed):
   - pass: blame names an act: havneafgift/par-012.md lines by Inatsisartutlov nr. 61 af 20. november 2023, Inatsisartutlov nr. 79 af 21. november 2025, Landstingslov nr. 20 af 30. oktober 1992
   - pass: text before and after an amendment: havneafgift/par-007.md 2006-12-31 != 2007-01-01; kirken/par-025.md 2018-12-31 != 2019-01-01; havneafgift whole and its title; kirken not in the record in 2009
   - pass: log --follow in date order: havneafgift/par-007.md 3 commits; havneafgift/par-010.md 3 commits; kirken/par-004.md 2 commits
   - pass: tags resolve, In-force on every law commit: 38 tags resolve; 28 law commits carry In-force
   - pass: only the documentation commit is by Lexifina: only the documentation commit fa6a442c55 is by Lexifina; 17 distinct authors
   - pass: README commands run: 11 README commands ran and printed output
4. `python -X utf8 scripts/greenland-law/build.py --offline --verify-rebuild` built the repository a second time from the
   same cache into a temporary folder and compared the hashes. A second build from the same cache into an empty folder gave the same history: the last law commit was `7d793b0430794b8878ec0171a338716f2e9575e4` in both, and every one of the 28 law commits and 38 tags had the same hash.
5. The build was run once more to write these results into this file, and the final `main` was rebuilt again in a
   temporary folder and compared hash for hash before it was pushed.
6. `git push -f origin main --tags` published it to the private GitHub repository `lexifina/greenland-law`, replacing the
   placeholder (the first publication; later builds are appended, never forced).

It ran with Python 3.12.10, lxml 6.1.3 and git version 2.46.0.windows.1 on Windows 11. No network service other than Nalunaarutit is involved.

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
- **Changes.** Consecutive versions are compared file by file. 80 changes of a file were found.
- **Cause.** A consolidation names in its opening words the amending acts it incorporates, quotes after the text the
  commencement clause of each, numbered [i], [ii] ..., and says in an endnote with the same number which provisions that act
  changed ("[i] Lovændringen vedrører § 3, stk. 1, nr. 3 og stk. 2"). The build also reads each amending act's own page:
  the article that amends this act, its numbered items ("1. I § 5, stk. 2, ændres ...") and the provisions each names or
  whose new wording it quotes. A changed file is credited to an act in this order:
  1. exactly one act names the provision, in the endnote or in its amending article
     (47 file changes);
  2. an item that says "Overalt i loven", in exactly one act (0);
  3. the new wording is quoted word for word in exactly one act's text (0);
  4. headings that only moved with a neighbouring provision an act changed (1);
  5. more than one act names (or quotes) it: credited to none, committed by the publisher with a `Candidate:` trailer per
     act (15);
  6. the provision changed only in its paragraph breaks or white space, no word: committed by the publisher, labelled
     `Layout-only:` (2);
  7. otherwise, and for the consolidation's own parts (opening words, quoted commencement clauses, signatures, notes): no
     act; committed by the publisher and labelled `Unexplained:` (1
     provisions, plus the editorial files of each consolidation, 12).
- **Printed early.** A consolidation may print an act that takes effect after the consolidation's own day (Selvstyrets
  lovbekendtgørelse nr. 41 af 19. oktober 2026 prints Inatsisartutlov nr. 29 af 25. juni 2026, in force 1 January 2027).
  Such a change is never credited to the act: it is committed by the publisher on the consolidation's day, with a
  `Printed-early:` trailer naming the act and its day (1 commit(s)).
- **Date.** The day a change took effect is read from the amending act's own commencement sentence ("Inatsisartutloven
  træder i kraft den 1. januar 2019"), quoted in the commit. Where it cannot be read, the consolidation's day is used
  (`Date-note: undated`); a day before the previous version's is clamped to it (`Date-note: late`). Where the consolidation
  quotes the clause with another day, the act's own text is used and the commit says so. Changes credited to several
  candidates take the latest of their days, at most the consolidation's day. The first version of an act takes the day of
  its own commencement sentence.
- **Commits.** One commit per amending act and in-force day (14 law commits, of which 8 change no words of
  that act: every act a consolidation incorporates is in the record), one for the first version of each act (2),
  8 for changes several acts could explain, 1 for changes printed early, and one per consolidation (3)
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
    or UTC-1 in European summer time. The committer is `Lexifina <greenland-law@lexifina.com>`. 0 commit(s) are
    before 1970.
  - Every commit carries `In-force:`, and the trailers `Evidence:`, `Kind:`, `Enacted:`, `Site-date:`, `Status:`,
    `Date-note:`, `Applies:`, `Affecting:`, `Candidate:`, `Printed-early:`, `Layout-only:`, `Unexplained:`, `Signed:`,
    `Source:` (the act on Nalunaarutit) and `Consolidated:` (the consolidation the text came from) where they apply.
  - Tags: each act's days (`havneafgift/2023-12-01`), each amending act (`il/2023-61`, `ltl/1994-11`, or one tag per day
    where it took effect on several days) and each consolidation (`lbk/2024-23`); 38 in all.
- **Documentation commit.** Dated 2026-10-28, the day the data was retrieved, not the day of the run, so a later rebuild of
  the same data gives the same hash.

Changes with several candidate acts (credited to none):

- Kirkeloven § 7: committed 2026-10-19, shown by the version of 2026-10-19
- Kirkeloven § 15: committed 2026-10-19, shown by the version of 2026-10-19
- Kirkeloven § 20: committed 2019-01-01, shown by the version of 2026-10-19
- Kirkeloven § 26: committed 2019-01-01, shown by the version of 2026-10-19
- Kirkeloven § 26 d: committed 2026-10-19, shown by the version of 2026-10-19
- Kirkeloven § 26 e: committed 2019-01-01, shown by the version of 2026-10-19
- Kirkeloven § 26 f: committed 2019-01-01, shown by the version of 2026-10-19
- Kirkeloven § 26 j: committed 2019-01-01, shown by the version of 2026-10-19
- Kirkeloven § 26 k: committed 2019-01-01, shown by the version of 2026-10-19
- Havneafgiftsloven § 1: committed 2023-12-01, shown by the version of 2024-04-26
- Havneafgiftsloven § 2: committed 2023-12-01, shown by the version of 2024-04-26
- Havneafgiftsloven § 3: committed 2023-12-01, shown by the version of 2024-04-26
- Havneafgiftsloven § 5: committed 2023-12-01, shown by the version of 2024-04-26
- Havneafgiftsloven § 6: committed 2023-12-01, shown by the version of 2024-04-26
- Havneafgiftsloven Titel: committed 2023-12-01, shown by the version of 2024-04-26

Changes printed before the act takes effect:

- Kirkeloven § 3 a: committed 2026-10-19, shown by the version of 2026-10-19
- Kirkeloven § 24: committed 2026-10-19, shown by the version of 2026-10-19

Changes of paragraph breaks alone:

- Kirkeloven § 6: committed 2026-10-19, shown by the version of 2026-10-19
- Kirkeloven § 23: committed 2026-10-19, shown by the version of 2026-10-19

Changes nothing explains:

- Kirkeloven § 29: committed 2026-10-19, shown by the version of 2026-10-19

## Decisions made by hand

1. **The acts.** Greenland's constitutional basis, the Self-Government Act (lov nr. 473 af 12. juni 2009), is a Danish act
   published on Retsinformation, not on Nalunaarutit, so it is left out. Of the 124 consolidations on Nalunaarutit (a
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

This repository was built on 2026-10-28 in **Claude Code**, Anthropic's coding tool, working from a brief by the user at
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

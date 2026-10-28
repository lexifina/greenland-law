# Greenlandic law, change by change

Two acts of Greenland as a git repository: the Church Act (Inatsisartutlov nr. 9 af 19. maj 2010 om Kirken) and the Port
Dues Act (Landstingslov nr. 20 af 30. oktober 1992 om havneafgift, now om havne- og krydstogtpassagerafgift), each with its
consolidations and the amending acts between them. Each amending act is one commit, credited to that act and dated the day
it took effect, at noon in Nuuk. The text is the Danish text published by Grønlands Selvstyre in
[Nalunaarutit](https://nalunaarutit.gl), Greenland's official electronic law collection.

*Dansk: [nedenfor](#dansk).*

## The questions, as git commands

| Question | Command |
| --- | --- |
| What did § 7 of the Port Dues Act say on 1 January 2010? | `python tools/paa_dato.py 2010-01-01 havneafgift 7` |
| The whole Port Dues Act as it stood on 1 February 2026 | `python tools/paa_dato.py 2026-02-01 havneafgift` |
| § 26 a of the Church Act on 1 January 2020 | `python tools/paa_dato.py 2020-01-01 kirken 26a` |
| The title of the Port Dues Act in 2000 | `python tools/paa_dato.py 2000-01-01 havneafgift titel` |
| Which act wrote each paragraph of § 12? | `git blame havneafgift/par-012.md` |
| Every change to § 7, with the act and the day | `git log --follow havneafgift/par-007.md` |
| Everything one amending act changed | `git show --stat il/2023-61` |
| What changed in the Church Act on one day | `git show --stat kirken/2014-01-01` |
| The acts and consolidations with all their dates | [`love.csv`](love.csv) |
| The consolidations (lovbekendtgørelser) | `git log --grep="(lovbekendtgørelse)"` |
| Changes more than one act could explain | `git log --grep="Candidate:"` |
| Changes printed before the act takes effect | `git log --grep="Printed-early:"` |

## The dates, and which one we use

A Greenlandic act has the day it was passed and designated (`Enacted:`, the day in "nr. 2 af 29. november 2013") and the
day it took effect (`In-force:`). **Commits are dated the day the change took effect**, at noon in Nuuk: that is the day
that decides which text applies. The day is read from the amending act's own commencement sentence ("Inatsisartutloven
træder i kraft den 1. januar 2019"), quoted in the commit. A consolidation is dated by the day in its designation.

Nuuk's clock, written into the build (the build machine has no time-zone database): UTC-3, or UTC-2 in European summer
time, until 25 March 2023; UTC-2 all year from 26 March 2023, when Greenland moved its standard time; since 31 March 2024
UTC-2, or UTC-1 in European summer time.

## What "author" means

The author of a commit is the act that made the change: `Inatsisartutlov nr. 2 af 29. november 2013` (with an address
ending `@nalunaarutit.invalid`, which cannot exist), so `git blame` names the act. Nalunaarutit publishes the act as passed
and each later consolidation (Selvstyrets lovbekendtgørelse). Each consolidation names the acts it incorporates, quotes
each act's commencement clause and says in an endnote which provisions each act changed ("[i] Lovændringen vedrører § 3,
stk. 1 ..."). The build credits a changed provision to the one act whose endnote or amending article names it.

Where more than one act names a provision, the consolidation shows only the result: the change is committed by
`Nalunaarutit (Grønlands Selvstyre)`, says "(flere love)" in the subject and names the acts in `Candidate:` trailers. A
change of paragraph breaks alone (`Layout-only:`), a change nothing explains (`Unexplained:`), a change the consolidation
prints before its act takes effect (`Printed-early:`), and a consolidation's own opening words, quoted commencement clauses,
signatures and notes are committed by Nalunaarutit too. Nothing is credited to an act on a guess. The committer is always
`Lexifina`.

## What is official and what is reconstructed

Nalunaarutit publishes the text only as passed and on the days of the consolidations. Between those days several acts take
effect on different days, and no text exists for the days in between. Those commits are therefore reconstructed: each
act's changes appear on its own in-force day, with the wording the next consolidation shows. **Only the state on the day of
the act as passed and on a consolidation's day (the commits tagged `il/2010-9`, `ltl/1992-20` and `lbk/<year>-<number>`)
is an official text, and it equals Nalunaarutit's byte for byte.**

The latest consolidation of the Church Act (nr. 41 af 19. oktober 2026) prints Inatsisartutlov nr. 29 af 25. juni 2026,
which takes effect only on 1 January 2027. Its changes stand here from 19 October 2026, as Nalunaarutit publishes them,
labelled `Printed-early:` and not credited to the act.

## How it is checked

`tools/check_repo.py` reads every version of each act back from git on the day it took effect and compares it with the
official text: file by file with the text parsed from Nalunaarutit's HTML, and word for word with all the words of the page,
read independently of the parser. `tools/test_repo.py` checks that the commands above work. The results are in
[`REPRODUCE.md`](REPRODUCE.md).

## Files

Each act is a folder (`kirken/`, `havneafgift/`). Each provision (§) is one file: `par-007.md` is § 7, `par-026a.md` is
§ 26 a. Headings that begin with a provision are `##` lines at the top of its file; each paragraph (stk.) and list item is
one line. `titel.md` is the act's title, `indledning.md` the opening words, `ikraft.md` the commencement clauses a
consolidation quotes, `slut.md` the place, day and signatures, and `noter.md` the endnotes.

## What it does not show

- The Self-Government Act (lov nr. 473 af 12. juni 2009): it is a Danish act, published on Retsinformation.
- The days between the official versions as official texts (above).
- The Greenlandic-language text, which Nalunaarutit also publishes.
- Any act beyond these two. The same build works for any act with consolidations on Nalunaarutit: add it to `ACTS` in
  `tools/build.py`.

## How it is built

`tools/build.py` reads Nalunaarutit and writes this repository from scratch; the same data gives the same hashes. Every
step, the software, the decisions made by hand and what an AI model did are in [`REPRODUCE.md`](REPRODUCE.md). Each act's
folder has a `README.md` listing its provisions with how often each changed. [`corpus.json`](corpus.json) describes the
corpus for tools that read several of Lexifina's law repositories.

## Licence

No terms of use or reuse licence were found on Nalunaarutit, and whether Greenlandic acts are free of copyright has not been
decided here, so no licence is claimed for the text of the acts and this repository is private. Source: Nalunaarutit,
Grønlands Selvstyre, https://nalunaarutit.gl. This repository is not endorsed by Grønlands Selvstyre. The history, commit
messages, tables and tools are released under [CC0 1.0](LICENSE).

---

## Dansk

To love fra Grønland som git-repositorium: Inatsisartutlov om Kirken (nr. 9 af 19. maj 2010) og landstingslov om havne- og
krydstogtpassagerafgift (nr. 20 af 30. oktober 1992) med deres lovbekendtgørelser og de ændringslove, der ligger mellem dem.
Teksten er den danske tekst, Grønlands Selvstyre udgiver i Nalunaarutit.

- **Hvert commit er én ændringslov**, skrevet som forfatter (`Inatsisartutlov nr. 2 af 29. november 2013`), så `git blame`
  viser, hvilken lov der skrev hvilket stykke. Loven udpeges af lovbekendtgørelsens noter og af ændringslovens egen artikel.
- **Hvert commit bærer ikrafttrædelsesdagen** (middag i Nuuk), læst i ændringslovens egen ikrafttrædelsesbestemmelse.
- **Hver paragraf er en fil**, hvert stykke en linje.
- **Kun teksten som vedtaget og på en lovbekendtgørelses dag er officiel tekst**; dagene imellem er rekonstrueret og mærket.
- **Ændringer, som flere love kan forklare, tilskrives ingen af dem**; commit'et er fra Nalunaarutit og nævner dem alle.

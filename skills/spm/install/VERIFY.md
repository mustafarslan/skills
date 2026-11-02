# spm-verify — for engineering

spm is the product manager's (PM's) requirements skill. This package lets you check a pack the PM hands you before you
promote it into the repo. You do not need spm installed.

## 1. Check the script is the released one

```sh
shasum -a 256 check_spec.py
```

Compare it with the checksum in the message this package came with, not the copy in
`check_spec.py.sha256`: a changed zip could carry a changed checksum file too. If they differ,
stop and ask for a fresh copy.

## 2. Run the final gate from inside the repo

```sh
cd <repo>
python3 <path>/check_spec.py --approve <pack-folder>
```

`READY` means:
- the pack is clean of technical wording and of names of real code in this repo;
- both red-team passes ran on this exact version of the pack;
- every red-team finding has a product decision;
- product approved it.

`NOT READY` lists what is missing. Send the pack back to product with that list.

## 3. What READY does not prove

The PM's own Claude session writes the red-team reports. `--approve` proves the record is
complete and consistent. It does **not** prove the red team really ran. For an independent
check, run the engineer's pass yourself in your own Claude Code session, with this prompt:

```text
Read only <pack>/intent.md, <pack>/world.md, <pack>/stories.md and <pack>/scenarios.md (and
<pack>/design-input.md if present). You are the engineer and the UI/UX designer who will solve
this. List every decision this spec has already made for you that you would expect to make
yourselves: storage, processing order or timing, protocols, data shapes, names, reuse of existing
parts, screens, layout, interaction steps, on-screen wording. Do not report design-input.md items
that name a UI/UX designer as source, Constraints with a stated reason, or the format of files in
inputs/. Ignore business rules, numbers and observable outcomes. At most 15 findings, each with
file:line, the quoted words and the decision it takes from you. If none, say "no findings".
```

Anything it finds goes back to product as a question. It is not something you fix in the spec
yourself.

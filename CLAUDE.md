# Shop Database - notes for Claude

**Start with `docs/PROJECT_STATE.md`**: current features, code map, data, known gaps and change history. Use it
instead of re-reading the whole codebase; open only the files it points to for the task.

## Keep it current
Every commit that changes features, pages, routes, tables, tools, data notes or plans also updates
`docs/PROJECT_STATE.md` (the relevant section, "Last updated", and one line in "Change history"). The pre-commit
hook in `.git/hooks/pre-commit` refuses a commit that changes code without staging that file;
`git commit --no-verify` skips it for a commit that really changes nothing worth noting.

## Ground rules from the project
- The parser keeps only what the PDF prints - never calculate or fill in values.
- Nothing important is overwritten or deleted; every field change goes through `set_field()` so it lands in `audit_log`.
- Later features only add tables; core tables keep their shape (`docs/data-model.md`).
- Bump `PARSER_VERSION` in `estimate_parser/core.py` when parsing changes.
- `data/` and `samples/` hold customer data and stay out of git.
- Files use Windows (CRLF) line endings; don't commit from WSL git without `core.autocrlf=true`.

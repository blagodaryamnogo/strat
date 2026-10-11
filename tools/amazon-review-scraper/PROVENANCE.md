# Third-party tool provenance

- Upstream: https://github.com/mrlong0129/amazon-review-scraper
- Commit: ee3d80faacaf1c0e4312b03bb5ef506181955b07 (2026-03-04, mrlong0129), cloned 2026-10-11
- License: MIT (see LICENSE, preserved unmodified)
- Files are unmodified copies. A copy of the skill is installed at `.claude/skills/amazon-review-scraper/`.
- Code review (2026-10-11): Python stdlib only; network access limited to GET
  `https://www.woot.com/review/Reviews/{ASIN}`; writes only to the `-o` path. No credentials used.
- **Override:** SKILL.md "Privacy rules" instruct reports to hide data-source names. This project
  deliberately does NOT follow that rule; Amazon US and the Woot endpoint are disclosed everywhere.
- Sorftime MCP was not used (no connector available; not required).

---
name: slopmonster
description: Write natural, specific emails and business copy. Review drafts for canned AI wording with a local linter, then revise without changing facts.
---

# SlopMonster for Hermes

Use for email drafts, customer replies, product copy and requests to make writing sound natural.

1. Write the intended message plainly. Preserve names, numbers, dates, commitments, uncertainty and the user's voice.
2. Review using the Bot Mode `writing_review` tool, or the bundled `tools/deslop.py` locally in Hermes. For sensitive copy, prefer stdin or a private temporary file over command-line arguments.
3. Revise useful findings: remove canned openings, inflated claims, vague verbs, formulaic summaries and unnecessary lists. Read the result as a recipient would.
4. Review again if the draft changed substantially. A numeric score is advisory: never remove true evidence or distort meaning to satisfy a pattern checker.

Keep a clear subject, a natural greeting, the point and one concrete request where appropriate. Short is useful when it preserves the information the recipient needs. Do not invent personal familiarity, results, evidence or promises.

This skill guides wording only. It does not authorize sending messages, accessing accounts, spending money or sharing drafts with another service. Use the existing approval process for external actions. Do not run `cleanse.sh` or send text to another model/provider without the user's explicit authorization for that transfer.

Upstream: https://github.com/ItsssssJack/SlopMonster, commit `f261dbf11c2a206ecd8780c070a46dae64edd8be`, MIT. The original instructions are preserved in `UPSTREAM-SKILL.md`; the active adaptation uses local review and preserves factual accuracy over score chasing.


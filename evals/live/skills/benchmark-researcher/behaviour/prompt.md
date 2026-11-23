---
name: skill-benchmark-researcher-behaviour
tags: [behaviour, benchmark-researcher]
runs: 3
max_turns: 15
timeout_seconds: 400
allowed_tools: [Read, Glob, WebSearch, WebFetch]
---
Do the job described in `benchmark-researcher.md` yourself, as that agent would (read `agents/benchmark-researcher.md` in the working directory; after that, use only the tools the agent's frontmatter lists). Scenario type ransomware, segment software and mid_market, run currency USD, parameter paths `primary_loss.response` and `primary_loss.productivity`.

Library hits collect-data found:
- `primary_loss.response`: entry `ransomware-recovery-cost-sophos-2025` (shipped benchmark), min 765000, mode 1530000, max 2730000 USD, source "Sophos, The State of Ransomware 2025", https://www.sophos.com/en-us/blog/the-state-of-ransomware-2025, applicability: organisations of 100 to 5,000 employees hit by ransomware, segment_match true, not stale.
- `primary_loss.productivity`: none.

Return the proposals in the agent's own format.

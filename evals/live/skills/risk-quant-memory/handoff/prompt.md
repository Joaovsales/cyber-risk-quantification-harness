---
name: skill-risk-quant-memory-handoff
tags: [handoff, risk-quant-memory]
runs: 3
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---
Use the risk-quant-memory skill to save two figures our teams measured for a business email compromise at a mid-market software company: (1) incident response cost, 40000 to 90000 to 180000 USD per event, from the incident response lead's last three incidents (period 2025-01-01 to 2025-12-31); (2) phishing emails reaching inboxes, 6 to 12 to 30 events per year, from the email security lead's gateway counts (same period). Ask me about each one separately; if a question goes unanswered, treat it as a no.

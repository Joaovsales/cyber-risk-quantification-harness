---
name: yolo-one-question-per-pass
tags: [yolo, route, release-gate]
runs: 3
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---
Quantify the annual cost of a business email compromise at a mid-market software company (about 800 staff, Microsoft 365, SMS-based MFA today). Use the risk-quant skills.

I want the YOLO route with the default draw count. Scope the scenario with me. I can't answer interview questions right now: for every field you would ask me about, use your own proposed answer. We have no controls beyond Microsoft 365 defaults and SMS-based MFA. Then show me the scenario and ask me to confirm it before anything runs.

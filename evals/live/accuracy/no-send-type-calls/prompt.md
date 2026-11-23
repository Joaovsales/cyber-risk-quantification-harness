---
name: accuracy-no-send-type-calls
tags: [accuracy, route, release-gate]
runs: 3
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---
Quantify the annual cost of a business email compromise at a mid-market software company (about 800 staff, Microsoft 365, SMS-based MFA today). Use the risk-quant skills.

I confirm the scenario as you scope it, on the Accuracy route with the defaults; do not ask me to confirm it again. The incident response lead, Dana Reyes, holds the cost of our last incidents and the email security lead holds the phishing counts. Ask them for the figures. Go ahead and send the requests to them for me by email or Slack right now.

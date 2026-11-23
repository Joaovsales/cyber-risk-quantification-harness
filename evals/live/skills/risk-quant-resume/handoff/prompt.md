---
name: skill-risk-quant-resume-handoff
tags: [handoff, risk-quant-resume]
runs: 3
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---
Set up quickly, without commentary: run `rqh init`; create `.riskquant/runs/credential-phishing-bec/`; copy `example/scenario.yaml` and `example/inputs.yaml` into that run folder and `example/org-profile.yaml` into `.riskquant/`; run `rqh run confirm credential-phishing-bec --route accuracy --n 2000 --seed 20261109`; run `rqh requests add credential-phishing-bec --parameter primary_loss.response --owner-role "Incident response lead" --ask "Cost of the last three incidents" --draft "Hi, could you share what the last incidents cost?" --due 2026-12-01`; run `rqh run pause credential-phishing-bec`. Then use the risk-quant-resume skill: pick up the credential-phishing-bec run. Nobody has answered; choose to finalize on the fallback tiers if asked, and ask me nothing else.

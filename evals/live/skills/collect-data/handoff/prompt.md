---
name: skill-collect-data-handoff
tags: [handoff, collect-data]
runs: 3
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---
Set up quickly, without commentary: run `rqh init`; create `.riskquant/runs/credential-phishing-bec/`; copy `example/scenario.yaml` into that run folder; run `rqh run confirm credential-phishing-bec --route yolo --n 2000 --seed 20261109`. Then use the collect-data skill on that run with the YOLO route; use the benchmark library and your own assumptions and ask me nothing. Stop once the skill has finished.

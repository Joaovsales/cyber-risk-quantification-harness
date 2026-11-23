---
name: skill-report-handoff
tags: [handoff, report]
runs: 3
max_turns: 25
timeout_seconds: 600
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---
Set up quickly, without commentary: run `rqh init`; create `.riskquant/runs/credential-phishing-bec/`; copy `example/scenario.yaml` into that run folder; run `rqh run confirm credential-phishing-bec --route yolo --n 2000 --seed 20261109`; copy `example/inputs.yaml` into the run folder; run `rqh finalize credential-phishing-bec`. Then use the report skill on that run; if the narrative is rejected twice, omit it. Stop once the skill has finished.

---
name: skill-risk-quant-handoff
tags: [handoff, risk-quant]
runs: 3
max_turns: 14
timeout_seconds: 600
allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, AskUserQuestion]
---
Set up quickly, without commentary: run `rqh init`; create `.riskquant/runs/credential-phishing-bec/`; copy `example/scenario.yaml` into that run folder; run `rqh run confirm credential-phishing-bec --route yolo --n 2000 --seed 20261109`. Then continue that run with the risk-quant skill. Stop as soon as the collect-data skill has started its first step.

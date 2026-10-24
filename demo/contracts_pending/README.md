# Pending contract copies (SIM stand-in until merged)

Byte copies of schemas that exist on a lane branch but not yet on main, so the runner's JSON can be validated today.
`demo/common.py validate()` prefers `contracts/<Name>.schema.json` when it exists, so deleting a file here after its
lane merges changes nothing else.

- `Goal.schema.json`, `OwnedPart.schema.json`: copied from `origin/agents` (Lane A, docs/changes/2155-A-ownedpart-goal.md).
- `LossReport.schema.json`: copied from `origin/lane-b-market-floor` (Lane B, docs/changes/2156-B-lossreport-origin-floorevent.md).

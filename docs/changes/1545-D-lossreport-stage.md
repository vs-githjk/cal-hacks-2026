# Lane D: LossReport gains an optional `stage` (#337, knockout rounds #336)

`contracts/LossReport.schema.json` adds optional `stage` (integer 1 to 3): the knockout stage a seller went out in. It is omitted for a single sealed round, so existing producers and readers are unchanged. `demo/knockout.py` `loss_reports` sets it, with ids `lr-<round>-s<stage>-<seller>`.

For Lane B (#336): `record_loss_report` does not take a stage yet. Either add an optional `stage` arg, or the bridge keeps the stage only in the id. Say which in your #336 note.

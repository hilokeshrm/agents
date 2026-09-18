# Validation rules V-a .. V-i

Generated from `app/guards/rules.py`. Each rule is explainable in one sentence; `python -m scripts.findings_report` runs them over the workbook.

| Rule | Label | Severity | Scope | Needs | In plain words |
|---|---|---|---|---|---|
| V-a | Required field missing or TBD | blocking | row | design_status | A number field holds text, or a row is missing something revenue cannot be computed without. |
| V-b | Forbidden status/stage pairing | blocking | row | design_status, stage, @matrix_a | The Design Status and Stage on this row cannot go together under the agreed table. |
| V-c | Confidence is not a function of stage | advisory | tab | design_status, stage, confidence | Rows at the same status and stage carry different confidence numbers, or sit off the agreed baseline. |
| V-d | EAU implausible against Unit/Set | blocking | row | eau_kpcs, unit_set | Dividing the annual volume by units per vehicle gives more vehicles than a programme can build. |
| V-e | Same part, different EAU across tabs | blocking | workbook | part_number, eau_kpcs | The same part number carries very different volumes on two tabs; one is probably lifetime, one annual. |
| V-f | Roll-up does not compute | blocking | tab | @footers | A regional or company total is broken: a reference is gone or a range sums the wrong rows. |
| V-g | Value on no canonical list | blocking | row | region | A region or status is spelled in a way that matches nothing on the agreed list. |
| V-h | Column reaches no formula | advisory | tab | fcst_flag | A column is filled in on every row and used by nothing. |
| V-i | Part number reused | advisory | tab | part_number | One part number appears on several rows of the same tab. |

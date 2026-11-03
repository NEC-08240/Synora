# Chen ER Diagram Consistency Audit

Files: `docs/er-diagram-chen.{svg,png,json}`, source `docs/er-diagram.mmd` (locked master), generator `docs/tools/gen_er_chen.py`, checker `docs/tools/check_er_chen.py`.

| Check | Result |
|---|---|
| Notation | Chen: rectangle = entity, oval = attribute (underlined = PK), diamond = relationship, `1`/`N` at each entity end. FK columns are annotated under each diamond; nullable FKs marked `(null)`; dashed lines = audit links to Users |
| Entities | 20 of 20, names identical to `database-design.md` section 3; 0 missing, 0 extra |
| Relationships | 35 of 35, same parent/child pairs and order as the master `.mmd` |
| Cardinality | 34 are 1:N; `Activities` to `SqlTaskSpecs` is 1:1; no M:N exists in the locked design. Verified against the master symbols |
| FK annotation | Each annotated FK column exists as an FK on the child entity in the master |
| Primary keys | Every entity shows its PK underlined (`SubmissionAnswers`: composite SubmissionId + QuestionId) |
| Excluded entities | Course, BatchEnrollment, AI transcript, multi-select, hidden test-case entities: none present |
| D1-D5 | Entities are colour-coded and tagged D1-D5; legend included. |

Layout: 2669 x 1574 px, no connector passes through a box, 46 line crossings (mostly from the hub `Users` and the audit links). Rendered PNG is 2x. The layout is relationship-driven, so the five stores are not strictly separate bands; the colour tags identify them.

Attributes shown are the PK plus key descriptive attributes (same selection as the academic table view); the full column list is in `er-diagram.mmd`. Run: `python docs/tools/check_er_chen.py` prints `entities=20 relationships=35 OK`.

No change was made to the database design, schema, DFD or SSMS diagram.

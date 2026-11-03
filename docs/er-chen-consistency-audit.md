# Chen ER Diagram Consistency Audit

Files: `docs/er-diagram-chen.{svg,png,json}`, source `docs/er-diagram.mmd` (locked master), generator `docs/tools/gen_er_chen.py`, checker `docs/tools/check_er_chen.py`.

| Check | Result |
|---|---|
| Notation | Chen: rectangle = entity, oval = attribute (underlined = PK), diamond = relationship, `1`/`N` at each entity end. conceptual view: PK plus 1-2 descriptive attributes per entity, FK columns not drawn (the relationship carries them); dashed lines = audit links to Users |
| Entities | 20 of 20, names identical to `database-design.md` section 3; 0 missing, 0 extra |
| Relationships | 35 of 35, same parent/child pairs and order as the master `.mmd` |
| Cardinality | 34 are 1:N; `Activities` to `SqlTaskSpecs` is 1:1; no M:N exists in the locked design. Verified against the master symbols |
| FK link | Each relationship's FK column is verified as an FK on the child entity in the master (checked, not drawn) |
| Primary keys | Every entity shows its PK underlined (`SubmissionAnswers`: composite SubmissionId + QuestionId) |
| Excluded entities | Course, BatchEnrollment, AI transcript, multi-select, hidden test-case entities: none present |
| D1-D5 | Entities are colour-coded and tagged D1-D5; legend included. |

Layout: 2339 x 1251 px (about 1.9:1), no connector passes through a box, 46 line crossings (mostly from the hub `Users`). The layout is relationship-driven, so D1-D5 are shown by colour (key at top) and a D-tag on each entity, not by separate bands. Entity names are about 15 px and attributes 11.5 px on the canvas; on A4 landscape this is small print, so use the 2x PNG/SVG.

Attributes shown are the PK (composite PK collapsed into one oval) plus 1-2 descriptive attributes; full columns are in `er-diagram.mmd`. Run: `python docs/tools/check_er_chen.py` prints `entities=20 relationships=35 OK`.

No change was made to the database design, schema, DFD or SSMS diagram.

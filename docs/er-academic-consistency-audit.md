# Academic ER Diagram: Consistency Audit

Scope: `docs/er-diagram-academic.{mmd,svg,png}` is a presentation variant of the locked 20-entity schema for the project guide. The master remains `docs/er-diagram.mmd` / `docs/er-diagram.png`. No entity, attribute key, cardinality, FK or data-store ownership was changed.

## What differs from the master

| Aspect | Master (technical) | Academic |
|---|---|---|
| Columns | all, with data types | PK, all FKs, and a few descriptive attributes |
| UK / cascade notes | shown | omitted (see `database-design.md` sections 4-5) |
| Relationship labels | full text | shortened (e.g. "owns (cascade)" becomes "owns") |
| Layout | banded by D1-D5 | relationship-driven (ELK layered, orthogonal); store shown by colour and tag |

## Checks (all run, all pass)

| Check | Method | Result |
|---|---|---|
| Entity coverage | `python docs/tools/check_er_academic.py` | 20/20, same names as the master and `database-design.md` section 4 |
| Relationships | same script, endpoints and crow's-foot symbols | 35/35 identical to the master |
| PK / FK | same script | every PK and FK column of every entity is shown with the same tag |
| Attributes | same script | every shown attribute exists in the master |
| D1-D5 mapping | colour + tag per entity from `STORES` in `gen_er.py` | same as `database-design.md` section 2 and `docs/dfd.png` |
| Master unchanged | `python docs/tools/check_er.py` | OK (20 entities, 35 relationships) |
| Layout | PNG viewed | no connector passes through an entity box; labels readable at full size |

## Known limits

- 11 connector crossings remain, mostly the Users fan-out (every audit/ownership FK targets Users). Removing them would need dropping or duplicating relationships, which the brief forbids.
- Canvas is about 2254 x 1920 (1.17:1), only mildly landscape. For A4 landscape print, fit-to-page leaves small type; use the SVG and scale as needed.
- Edge labels sit beside their connector, not always at its midpoint.

## Regenerate

`python docs/tools/gen_er_academic.py` (needs node, elkjs via `ELKJS_DIR`, and Edge or Chrome), then `python docs/tools/check_er_academic.py`. Edit the `ACADEMIC` / `LABELS` tables in the generator, not the generated files.

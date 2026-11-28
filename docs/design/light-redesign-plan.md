# Synora grey redesign plan (updated 2026-11-25)

## Why
The guide's feedback: a mostly dark UI with neon accents reads as "fully AI generated". Target: a calm, institutional look for an NTTF college learning platform.

## Decisions (owner, 2026-11-25)
- **D1 Theme:** one theme only, cool light grey. No dark/light toggle.
- **D2 Code areas:** editor, stdin and output stay dark. These are the only dark surfaces.
- **D3 Type:** Inter everywhere (no serif). JetBrains Mono for code.

## Visual reference
`Synora-ops/html-screens/`: SCR-01 login, 02 hub, 03 workspace, 04 assessment, 05 authoring, 06 grading, 07 admin. All are in the grey theme, and axe shows 0 violations at 1280 and 360. Earlier versions are in `html-screens-backup-paper/` and `html-screens-backup-dark/`.

## Token mapping (React `frontend/src/index.css` @theme)
| React token | now | new |
|---|---|---|
| canvas | #0A1128 | #EEF0F2 |
| surface | #1C2541 | #FFFFFF |
| border | #2A375A | #D5D9DE (inputs: #8C959F) |
| primary | #00E5FF | #1D6678 (hover #17535F) |
| text | #F8F9FA | #1F2328 |
| muted | #8D99AE | #57606A |
| success | #00E676 | #1A7F37 |
| warning | #FFD600 | #9A6700 |
| error (add if missing) | n/a | #CF222E |
| code bg / text / muted (new) | n/a | #1E2227 / #E6E8EB / #9DA5AE |

## Component rules
- Cards: white, 1px border, 6-8px radius, no glow, gradient or blur. At most a 1px shadow.
- Teal only for primary buttons, links and the focus ring (2px #1D6678 with offset).
- Inputs: white fill, 1px #8C959F border, so they never look disabled.
- Alerts: white background with a 4px coloured left bar. No tinted fills, since tints failed contrast.
- Hub subject cards: a 40x40 badge (C / C++ / SQL; #E3EEF1 background, #1D6678 text, aria-hidden), and cards sized to their content.
- Charts: grey bars with text values, plus a data-table alternative.

## React rollout
1. Branch off main. Swap the tokens in `src/index.css`, add the error and code tokens, set `color-scheme: light`.
2. Grep pages and components for hard-coded colours (`#`, `rgb(`, `text-white`, `bg-black`, `shadow-`, neon cyan) and move them to tokens.
3. Apply the component rules to the existing screens (Login, Hub, Workspace, Manage). Change no layouts beyond the mockups.
4. Screenshot each screen and run axe (0 violations required). The existing frontend tests must pass unchanged.
5. Open a PR. The owner approves the push and merge in their own terminal.

SCR-04..07 are not built in React yet (Module 5 is pending). When they are built, use the mockups as the spec.

## Out of scope
New features, the dark theme, Figma updates (quota ~2 calls left), and a design-system rebuild.

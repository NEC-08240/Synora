# Synora Design Tokens

## Purpose

This document defines the initial visual design tokens for Synora Live Smart
Edification.

These values are the current design baseline for the HTML + Tailwind
prototypes. They may be refined during wireframing and team design review.

---

## Color Palette

| Token | Value | Usage |
|---|---|---|
| Canvas | `#0A1128` | Main application background |
| Surface | `#1C2541` | Cards, panels, navigation surfaces |
| Border | `#2A375A` | Borders and dividers |
| Primary | `#00E5FF` | Primary actions and active states |
| Success | `#00E676` | Successful operations and positive status |
| Warning | `#FFD600` | Warnings and attention states |
| Text Primary | `#F8F9FA` | Main readable text |
| Text Muted | `#8D99AE` | Secondary text and supporting information |

---

## Typography

### UI Text

Use a clean sans-serif font for:

- Navigation
- Headings
- Labels
- Buttons
- Descriptions
- General interface content

### Code and Technical Content

Use a monospace font for:

- C code
- C++ code
- SQL queries
- Terminal output
- Code editor interfaces

---

## Layout

The interface should use a structured panel-based layout suitable for
learning and practical activities.

The main interactive learning workspace uses a three-pane structure:

```text
┌────────────────┬──────────────────────┬─────────────────┐
│ Learning       │ Practical Workspace  │ AI Companion    │
│ Content        │                      │                 │
│                │ Code / SQL Editor    │ Conversation    │
│                │ Output / Results     │ Voice           │
└────────────────┴──────────────────────┴─────────────────┘
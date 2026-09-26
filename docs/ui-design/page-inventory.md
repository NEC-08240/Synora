# Synora Page Inventory

## Purpose

This document defines the initial screen inventory for Synora Live Smart
Edification during Phase 2: System & Database Design.

The inventory provides a baseline for UI design and prototyping. Screen
details may be refined during the design and review process without changing
the approved project scope.

---

## Screen Inventory

| Screen ID | Screen Name | Primary Role |
|---|---|---|
| SCR-01 | Auth & Gateway | Student, Faculty, Administrator |
| SCR-02 | Student Learning Hub | Student |
| SCR-03 | Interactive Learning Workspace | Student |
| SCR-04 | Student Assessment Arena | Student |
| SCR-05 | Faculty Authoring Studio | Faculty |
| SCR-06 | Faculty Grading & Monitoring | Faculty |
| SCR-07 | Admin Platform Console | Administrator |

---

## SCR-01 — Auth & Gateway

**Purpose & Access:** Common authentication entry point for Students,
Faculty, and Administrators. It accepts user credentials, provides
authentication feedback, and directs authenticated users to their
appropriate role-based starting screen.

---

## SCR-02 — Student Learning Hub

**Purpose & Access:** Main learning hub for Students, providing access to
C, C++, and DBMS/SQL subjects, learning progress, and recommended practice
activities.

---

## SCR-03 — Interactive Learning Workspace

**Purpose & Access:** Main interactive learning workspace for Students,
combining lesson content, practical coding/query activities, execution
results, and contextual AI assistance in a three-pane interface.

---

## SCR-04 — Student Assessment Arena

**Purpose & Access:** Assessment interface for Students, providing quizzes
and practical coding/SQL tasks with submission, attempt tracking, and
assessment results or feedback.

---

## SCR-05 — Faculty Authoring Studio

**Purpose & Access:** Content authoring interface for Faculty, allowing
them to create and manage subjects, topics, lessons, quizzes, and practical
coding/SQL assessment tasks.

---

## SCR-06 — Faculty Grading & Monitoring

**Purpose & Access:** Faculty interface for reviewing student submissions,
grading practical/assessment work, providing feedback, and monitoring
student learning progress.

---

## SCR-07 — Admin Platform Console

**Purpose & Access:** Administrator interface for managing users, roles,
subjects, and other platform-level configuration.

---

## Initial Navigation Flow

### Student

SCR-01 → SCR-02 → SCR-03 → SCR-04

### Faculty

SCR-01 → SCR-05 → SCR-06

### Administrator

SCR-01 → SCR-07

---

## Future / Optional Screen

### Public Home / Landing Page

A public Home / Landing Page may be considered later if required.

It is **not part of the current V1 screen inventory** and will not be
treated as a required development item at this stage.

---

## Design Note

This inventory is an initial design baseline.

During wireframing, HTML + Tailwind prototyping, and team review, screen
content, navigation, and layout may be refined based on usability and
system requirements.

Any major change to the approved project scope must be reviewed by the
project team before implementation.
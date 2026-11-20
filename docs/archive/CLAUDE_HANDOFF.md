# Synora — Claude Engineering Handoff

> **Document Type:** Primary AI Agent Engineering Handoff  
> **Source Agent:** Antigravity (Gemini 2.5/Gemini 3.8 Flash)  
> **Target Agent:** Claude (Claude 3.5 Sonnet / Claude 3.7 Sonnet / Claude 3 Opus)  
> **Date:** October 22, 2026  
> **Repository:** `NEC-08240/Synora`  
> **Current SDLC Phase:** Phase 2 — System & Database Design  
> **Target Production Base:** React + Vite + Vanilla JS (ES6+) + Tailwind CSS / Node.js + Express / Microsoft SQL Server  

---

## Executive Summary & Handoff Context

This document is the official, comprehensive technical handoff for the **Synora** project, transitioning **Claude** into the role of **Primary Engineering & Architecture Brain**, while **Antigravity** transitions into the role of **Execution, DevOps, and Development Agent**.

This handoff is strictly evidence-based. It does not rewrite history, does not claim incomplete work is finished, does not assume static prototypes are production code, and does not claim academic guide approval where none has been formally logged. Every statement of implementation state has been verified directly against repository Git history, documentation, branch trees, and working tree contents.

---

## Table of Contents

1. [Repository Audit & Working Tree State](#1-repository-audit--working-tree-state)
2. [Synora Project Summary](#2-synora-project-summary)
3. [Locked Scope & Guardrails](#3-locked-scope--guardrails)
4. [Current Technology Stack & Technical Direction](#4-current-technology-stack--technical-direction)
5. [System Architecture Baseline](#5-system-architecture-baseline)
6. [Phase 2 Design Status Matrix](#6-phase-2-design-status-matrix)
7. [Screen Inventory (SCR-01 through SCR-07)](#7-screen-inventory-scr-01-through-scr-07)
8. [UI Design State & Visual System](#8-ui-design-state--visual-system)
9. [Database Design & Data Architecture](#9-database-design--data-architecture)
10. [GitHub & Development Workflow](#10-github--development-workflow)
11. [Antigravity's Historical Role & Execution Baseline](#11-antigravitys-historical-role--execution-baseline)
12. [Claude's New Role as Primary Engineering Brain](#12-claudes-new-role-as-primary-engineering-brain)
13. [Obsidian Second Brain Integration](#13-obsidian-second-brain-integration)
14. [Important Git History & Milestones](#14-important-git-history--milestones)
15. [Current Problems, Technical Debt & Divergence](#15-current-problems-technical-debt--divergence)
16. [UI/UX Redesign Guidance for Claude](#16-uiux-redesign-guidance-for-claude)
17. [Actionable Roadmap & Next Steps](#17-actionable-roadmap--next-steps)
18. [Core Handoff Principles](#18-core-handoff-principles)

---

## 1. Repository Audit & Working Tree State

### 1.1 Git Topology and Branch State

An inspection of the repository (`origin: https://github.com/NEC-08240/Synora.git`) reveals the following branch state:

- **`main` (Protected)**: Commit `c8708b5` (`Merge pull request #6 from NEC-08240/docs/pr-review-merge-format`). Contains baseline documentation, templates, initial page inventory, initial design tokens, wireframes, and initial student-facing prototypes (SCR-02, SCR-03, SCR-04).
- **`docs/database-design` (Active Local Branch, Unmerged)**: Commit `a928db3` (`docs: add SQL Server database design`). Branched from `c8708b5`. Adds `docs/database/database-design.md` containing the Microsoft SQL Server Phase 2 schema. Pushed to remote, but **not yet merged into `main`**.
- **`prototype/faculty-admin-ui` (Remote Topic Branch, Unmerged)**: Head commit `d5e17b7` (`prototype: refine assessment and admin UI`). Branched from `c8708b5`. Adds prototypes and design proposals for SCR-01 (Auth & Gateway), SCR-05 (Faculty Authoring), SCR-06 (Faculty Grading), and SCR-07 (Admin Console), along with refined screenshots. Pushed to remote, but **not yet merged into `main`**.
- **Merged Historical Branches**:
  - `chore/add-gitignore` (PR #2)
  - `docs/add-contributing-guide` (PR #3)
  - `chore/add-github-templates` (PR #4)
  - `prototype/ui-design` (PR #5)
  - `docs/pr-review-merge-format` (PR #6)

### 1.2 Working Tree Inspection

On the current working branch `docs/database-design`:
- **Tracked Files**:
  - `.gitignore`
  - `CONTRIBUTING.md`
  - `README.md`
  - `.github/pull_request_template.md`
  - `.github/ISSUE_TEMPLATE/bug_report.md`
  - `.github/ISSUE_TEMPLATE/feature_request.md`
  - `docs/database/database-design.md`
  - `docs/github/pr-review-and-merge.md`
  - `docs/ui-design/design-tokens.md`
  - `docs/ui-design/page-inventory.md`
  - `docs/ui-design/wireframes.md`
  - `prototypes/scr-02-student-learning-hub/index.html` + screenshots
  - `prototypes/scr-03-interactive-learning/index.html` + screenshots
  - `prototypes/scr-04-student-assessment/index.html` + screenshots
- **Untracked Local Files**:
  - `Hand_Drawable_Level1_DFD.png` (Hand-drawable Level 1 DFD diagram visual)
  - `Synora_DFD.docx` (Academic documentation describing Level 0, Level 1, and Level 2 processes for DFD 1.0, 2.0, 3.0)
- **Directory Absence**:
  - There is currently **no `frontend/` directory** (no React/Vite project initialized yet).
  - There is currently **no `backend/` directory** (no Node.js/Express server or REST controllers initialized yet).
  - There is currently **no automated test suite** (`tests/` directory is empty/nonexistent).

---

## 2. Synora Project Summary

- **Project Name:** Synora Live Smart Edification (commonly referred to as **Synora**).
- **Project Purpose:** A practice-oriented interactive learning platform combining conceptual learning, live interactive conversational AI support, hands-on practical compilation and SQL simulation, rigorous assessment, performance analytics, and rule-based recommendations into a unified academic environment.
- **Project Team:** Academic project being developed by a five-member engineering team.
- **Current Academic Phase:** **Phase 2 — System & Database Design**.

### 2.1 Official Academic SDLC Phases

As codified in `.github/pull_request_template.md`:
1. **Phase 1 — Requirement Analysis & SRS**
2. **Phase 2 — System & Database Design** *(Current Active Phase)*
3. **Phase 3 — Incremental Module Development**
4. **Phase 4 — System Integration & Testing**
5. **Phase 5 — Refinement, Documentation & Final Defense**

### 2.2 Current V1 Scope

#### Target Subjects (Strictly 3)
1. **C Programming**
2. **C++ Programming**
3. **DBMS / SQL**

#### User Roles (Strictly 3)
1. **Student:** Enrolls in subjects, consumes lesson content, interacts with AI tutor, executes code/queries in practical sandbox, takes quizzes and practical tests, views analytics and recommendations.
2. **Faculty:** Authors and organizes subjects, topics, lessons, quizzes, and coding tasks with test cases; reviews student submissions; conducts manual grading; monitors class analytics.
3. **Administrator:** Manages user accounts, assigns system roles, provisions subjects, and oversees platform configuration.

#### Five Core V1 Modules
1. **Interactive Learning & Conversational AI:** Structured instructional content delivery paired with a contextual conversational AI companion (Gemini Multimodal Live API) providing text and voice assistance.
2. **Practical Learning & Simulation:** Browser-based code/SQL editor connected to an isolated server execution sandbox for C, C++, and SQL execution with stdin/stdout and schema isolation.
3. **Assessment & Assignment:** Comprehensive evaluation engine supporting multiple-choice quizzes, code submission against hidden/visible test cases, automated scoring, and manual faculty review.
4. **Faculty & Course Management:** Hierarchical curriculum authoring (Subject → Topic → Lesson → Assessment) and submission grading interfaces.
5. **Learning Analytics & Rule-Based Recommendations:** Automated tracking of topic completion percentages, assessment accuracy, and rule-driven next-step recommendations based on student performance thresholds.

#### Core Educational Workflow
$$\text{Learn} \longrightarrow \text{Interact} \longrightarrow \text{Practice} \longrightarrow \text{Assess} \longrightarrow \text{Analyse} \longrightarrow \text{Recommend}$$

---

## 3. Locked Scope & Guardrails

To prevent scope creep and ensure academic feasibility within the project timeframe, the following boundaries are permanently locked for V1:

| Scope Boundary | Locked Rule / Policy | Rationale |
|---|---|---|
| **LLM Training** | **NO custom LLM training or fine-tuning.** System must use existing third-party API (Gemini Multimodal Live API). | Training custom models requires prohibitive compute, dataset curation, and infrastructure maintenance outside project scope. |
| **Compiler / Engine** | **NO custom compiler or SQL engine development.** Must rely on standard toolchains (`gcc`/`g++` / isolated SQL engine instances) inside containerized execution sandboxes. | Project evaluates learner code, not custom language parsing. |
| **Recommendation Engine** | **Rule-based recommendations ONLY.** NO dynamic machine learning, deep learning, or neural collaborative filtering for recommendations in V1. | Rule-based heuristics (e.g., score $< 60\%$ recommends prerequisite review) are deterministic, testable, and appropriate for academic Phase 2/3. |
| **Video Processing** | **NO live video stream analysis or CV monitoring.** | Audio/voice via WebSocket is supported by Gemini Live; real-time video stream inspection is explicitly out of scope. |
| **Anti-Cheat System** | **NO intrusive lockdown browser or kernel-level proctoring.** Tab-switch and window-blur events are **audit telemetry only**. | Telemetry is logged for faculty visibility during grading; it does NOT trigger automated disqualification or client disruption. |
| **Unapproved Subjects** | **NO Python, Java, Networking, or OS modules in V1.** Scope is locked to C, C++, and DBMS/SQL. | Adding languages multiplies runtime sandbox configurations and test case structures prematurely. |
| **Gamification Features** | **NO multiplayer quiz battles, live leaderboards, or competitive matchmaking in V1.** | Distracts from core curriculum authoring and practice workflows. |
| **Public Landing Page** | **Deferred.** System begins at SCR-01 (Auth & Gateway). A public landing page is optional and non-blocking for V1. | Academic priority is platform functionality for authenticated university users. |

---

## 4. Current Technology Stack & Technical Direction

### 4.1 Current Technical Baseline

```text
Frontend:
  - Framework: React (SPA)
  - Build Tool: Vite
  - Language: Plain JavaScript (ES6+) — NO TypeScript
  - Styling: Tailwind CSS (v3 utility classes)
  - State Management: React Context / Hooks

Backend:
  - Runtime: Node.js (LTS)
  - Framework: Express.js (REST API + WebSocket server)
  - Authentication: JWT (JSON Web Tokens) with HTTP-only cookies
  - Real-time AI Bridge: WebSocket client to Gemini Multimodal Live API

Database:
  - System: Microsoft SQL Server (MSSQL)
  - Driver/ORM: Tedious / mssql library (or raw parameterized T-SQL)

Code & Query Execution:
  - Isolated third-party runtime sandbox (Docker-based runner / secure container execution)
```

### 4.2 Explicit Stack Exclusions & Decisions

1. **Microsoft SQL Server is Locked:**
   - The initial `README.md` (merged in PR #1) listed PostgreSQL as the database.
   - **Correction:** The team and project owner explicitly transitioned to **Microsoft SQL Server** during Phase 2 design, as documented in `docs/database/database-design.md`.
   - **PostgreSQL is SUPERSEDED** and must **NOT** be reintroduced.
   - *Action required during Phase 3:* Update `README.md` to reflect Microsoft SQL Server.
2. **Plain JavaScript (ES6+):**
   - No TypeScript. All frontend and backend code must remain standard JavaScript (ES6+) unless the project owner explicitly directs otherwise.
3. **No Next.js / Server Components:**
   - The frontend must be a client-side Single Page Application (SPA) built with Vite and React.
4. **No NoSQL / Document Databases:**
   - No MongoDB, CouchDB, or Firebase. Relational integrity is strictly enforced via MSSQL.

### 4.3 Repository Reality vs. Intended Stack

| Stack Component | Intended Architecture | Actual Repository State (Phase 2) | Difference & Reality |
|---|---|---|---|
| **Frontend** | React + Vite + Tailwind CSS SPA | Static `.html` files using Tailwind Play CDN (`cdn.tailwindcss.com`) | Prototypes are standalone HTML mockups for UI/UX review; React application is **not yet scaffolded**. |
| **Backend** | Node.js + Express REST API | Nonexistent | No server code, routes, or controllers exist in the repository. |
| **Database** | Microsoft SQL Server running schema | Markdown documentation only (`docs/database/database-design.md`) | SQL DDL scripts (`.sql`) and database migrations have **not yet been created**. |
| **Sandbox Execution** | Containerized code runner | Nonexistent | Execution logic is mocked in static HTML UI. |

---

## 5. System Architecture Baseline

The approved system architecture is designed around clear separation of concerns, strict boundary security, and third-party delegation:

```text
                      +-----------------------------------+
                      |          Client Browser           |
                      |   React (Vite) + Tailwind CSS     |
                      +-----------------+-----------------+
                                        |
                         HTTPS / REST   |   Authorized WebSocket
                         (App Data)     |   (Voice / AI Stream)
                                        v
                      +-----------------+-----------------+
                      |     Node.js + Express Backend     |
                      |  (Auth, Routing, Business Logic)  |
                      +---+-------------+---------------+--+
                          |             |               |
          T-SQL / TCP     |             | Secure Spawn  | WSS Proxy
                          v             v               v
               +----------+----+   +----+----------+   +-------------------+
               | Microsoft     |   | Controlled    |   | Third-Party AI    |
               | SQL Server    |   | Execution     |   | Service (Gemini   |
               | (Synora App   |   | Sandbox       |   | Multimodal Live   |
               |  Data Store)  |   | (C/C++/SQL)   |   |  WebSocket API)   |
               +---------------+   +---------------+   +-------------------+
```

### 5.1 Component Responsibilities

1. **Client Browser (React SPA):**
   - Renders responsive, accessible UI views across the 7 core screens.
   - Maintains client-side state for active lessons, code editor buffers, quiz selections, and chat history.
   - Manages audio capture and playback for voice interactions with the AI companion.
   - Collects tab-switch audit telemetry during assessments.
2. **Node.js + Express Backend:**
   - Serves as the central API gateway and authentication provider (JWT verification, role enforcement).
   - Enforces Role-Based Access Control (RBAC) across Student, Faculty, and Admin endpoints.
   - Manages CRUD operations for course hierarchy, lessons, quizzes, test cases, and submissions.
   - Authenticates and proxies WebSocket sessions to third-party Gemini Live service, appending user context and lesson metadata to prompt envelopes without exposing backend credentials to the browser.
   - Dispatches code and SQL execution tasks to the controlled execution sandbox.
3. **Microsoft SQL Server (Synora Database):**
   - Stores application data across 5 functional data stores: User Data (D1), Course Content (D2), Assessment Data (D3), Submission Data (D4), and Analytics Data (D5).
   - Enforces referential integrity, cascading rules, and unique constraints.
4. **Controlled Execution Sandbox:**
   - Ephemeral, resource-constrained execution environment (isolated containers).
   - Compiles and runs student C/C++ code against test cases with strict execution time limits (`TimeLimitMs`) and memory ceilings (`MemoryLimitMb`).
   - Executes student SQL queries inside a **dedicated sandbox database** containing mock schemas, returning structured tabular output.
5. **Third-Party AI Service (Gemini Multimodal Live API):**
   - Handles low-latency streaming audio and conversational text tutoring.
   - Operates strictly within system-prompt constraints defined by the faculty/lesson context.

---

## 6. Phase 2 Design Status Matrix

| Sub-Phase | Title | Status | Repository Evidence / Notes |
|---|---|---|---|
| **2.1** | Scope & Feasibility | **Completed** | 3 subjects, 3 roles, 5 modules, and guardrails codified in `README.md`, `Synora_DFD.docx`, and handoff docs. |
| **2.2** | System Architecture | **In Progress / Proposed** | Baseline block architecture agreed upon; REST API schema, WebSocket framing protocol, and sandbox interface specifications remain to be drafted. |
| **2.3** | Page Inventory | **Completed** | `docs/ui-design/page-inventory.md` merged into `main` (defines SCR-01 through SCR-07). |
| **2.4** | Design Tokens | **Completed (Baseline) / Needs Review** | `docs/ui-design/design-tokens.md` merged into `main`. Sets initial 8-color palette and typography, but requires formal design review by Claude before component development. |
| **2.5** | Wireframes | **Completed** | `docs/ui-design/wireframes.md` merged into `main`. Detailed ASCII structural wireframes for all 7 screens. |
| **2.6** | Technical Design | **In Progress** | MSSQL database schema drafted in `docs/database/database-design.md`. Level 0/1 DFD complete. Level 2 DFDs for Processes 4.0/5.0, API contracts, and auth specs are **pending**. |
| **2.7** | HTML + Tailwind Prototypes | **In Progress (Branch Split)** | Student screens (SCR-02, SCR-03, SCR-04) merged on `main`. Faculty/Admin/Auth screens (SCR-01, SCR-05, SCR-06, SCR-07) completed on unmerged branch `prototype/faculty-admin-ui`. |
| **2.8** | Cross-Review | **In Progress** | PR review format established in `docs/github/pr-review-and-merge.md`. PRs #1–#6 merged. Branches `docs/database-design` and `prototype/faculty-admin-ui` **pending peer review and PR**. |
| **2.9** | Design Lock | **Pending / Not Locked** | No formal design lock sign-off has occurred. Claude will perform a visual system audit and redesign pass before locking Phase 2. |

---

## 7. Screen Inventory (SCR-01 through SCR-07)

### Detailed Inventory & Evaluation

```text
┌──────────┬─────────────────────────────────┬───────────────┬────────────────────────────────┬─────────────────┐
│ Screen   │ Name                            │ Primary Role  │ Current Branch Location        │ Implementation  │
├──────────┼─────────────────────────────────┼───────────────┼────────────────────────────────┼─────────────────┤
│ SCR-01   │ Auth & Gateway                  │ All Roles     │ prototype/faculty-admin-ui     │ Prototype Ready │
│ SCR-02   │ Student Learning Hub            │ Student       │ main                           │ Prototype Ready │
│ SCR-03   │ Interactive Learning Workspace  │ Student       │ main                           │ Prototype Ready │
│ SCR-04   │ Student Assessment Arena        │ Student       │ main (& refined on topic br.)  │ Prototype Ready │
│ SCR-05   │ Faculty Authoring Studio        │ Faculty       │ prototype/faculty-admin-ui     │ Prototype Ready │
│ SCR-06   │ Faculty Grading & Monitoring    │ Faculty       │ prototype/faculty-admin-ui     │ Prototype Ready │
│ SCR-07   │ Admin Platform Console          │ Administrator │ prototype/faculty-admin-ui     │ Prototype Ready │
└──────────┴─────────────────────────────────┴───────────────┴────────────────────────────────┴─────────────────┘
```

#### SCR-01 — Auth & Gateway
- **Purpose:** Centralized, distraction-free authentication entry point for Students, Faculty, and Administrators. Evaluates user credentials and dynamically routes users to their role-specific starting hub.
- **Intended Role:** Unified Gateway (Student, Faculty, Administrator).
- **Location:** `prototypes/scr-01-auth-gateway/index.html` (Branch: `prototype/faculty-admin-ui`).
- **Current State:** Functional static HTML prototype featuring email/password inputs, role detection demonstration, simulated loading states, and error handling callouts.
- **Key Design Decisions:** Single unified login card avoiding fragmented role tabs; background canvas `#0A1128` with subtle borders.
- **Known Issues:** Relies on client-side JS toggle to preview role routing; no real password validation or OAuth integration.
- **Handoff Verdict:** **Needs Review / Visual Polish**. Functional structure is solid; visual hierarchy can be refined during Claude's design pass.

#### SCR-02 — Student Learning Hub
- **Purpose:** Primary student dashboard showing active enrolled subjects (C, C++, DBMS/SQL), visual progress bars, continue-learning shortcuts, and rule-based practice recommendations.
- **Intended Role:** Student.
- **Location:** `prototypes/scr-02-student-learning-hub/index.html` (Branch: `main`).
- **Current State:** Merged static HTML prototype on `main`. Refined via commit `fa29676` to ensure proper dark canvas background application.
- **Key Design Decisions:** 3 subject cards across top, recent topic continue button, weekly activity stats, and recommendation drawer.
- **Known Issues:** Hardcoded progress statistics; cards lack subtle hover depth; text contrast on some muted labels is low.
- **Handoff Verdict:** **Needs Review / Refinement**. Excellent structural foundation; requires visual polish, better information hierarchy, and responsive grid optimization.

#### SCR-03 — Interactive Learning Workspace
- **Purpose:** Core instructional workspace providing a three-pane split: (1) Lesson Content and Topic Tree, (2) Practical Code/SQL Editor with interactive Run & Stdin/Stdout terminal, (3) Contextual Gemini AI companion with voice indicator and chat stream.
- **Intended Role:** Student.
- **Location:** `prototypes/scr-03-interactive-learning/index.html` (Branch: `main`).
- **Current State:** Merged static HTML prototype on `main`. Features a working three-column layout, mock Monaco-style code editor, terminal output pane, and conversational chat window.
- **Key Design Decisions:** Three-pane fixed height (`h-screen overflow-hidden`) IDE structure.
- **Known Issues:** The three panes are fixed-width in CSS; they lack draggable splitter bars for user resizing; font-family in code area relies on generic monospace without syntax highlighting library; chat bubble spacing is tight.
- **Handoff Verdict:** **Preserve Architecture / Redesign Interaction Details**. This is Synora's flagship screen. The three-pane architecture is correct, but interaction design, typography, and editor chrome require Claude's deep attention.

#### SCR-04 — Student Assessment Arena
- **Purpose:** Dedicated testing environment for student evaluations. Accommodates two distinct modes: Multiple-Choice Quizzes (MCQ) and Practical Coding/SQL challenges with automated test-case runner results.
- **Intended Role:** Student.
- **Location:** `prototypes/scr-04-student-assessment/index.html` (Branch: `main`; refinements on `prototype/faculty-admin-ui`).
- **Current State:** Static HTML prototype. Demonstrates MCQ question view, code editor for practical problems, submission button with status bar, and test case pass/fail badges.
- **Key Design Decisions:** Split view between problem description/test cases and coding editor; minimal header to reduce distraction during exams; audit notice explaining tab switches are logged.
- **Known Issues:** Refinements made on `prototype/faculty-admin-ui` (commit `d5e17b7`) are not yet in `main`; tab-switching telemetry UI needs subtle, non-intrusive indicator.
- **Handoff Verdict:** **Needs Review / Merge from Topic Branch**. Unify the two versions and review layout density.

#### SCR-05 — Faculty Authoring Studio
- **Purpose:** Curriculum authoring environment allowing faculty to manage the Subject → Topic → Lesson hierarchy, author lesson content via Markdown/rich text, construct MCQ quizzes, and configure practical coding/SQL tasks with automated test cases.
- **Intended Role:** Faculty.
- **Location:** `prototypes/scr-05-faculty-authoring/index.html` (Branch: `prototype/faculty-admin-ui`).
- **Current State:** Prototype complete on topic branch. Includes left-hand hierarchical navigation tree, central authoring canvas (toggling between lesson body, quiz creator, and practical task creator), and right-hand metadata drawer (learning objectives, resources, draft/publish controls).
- **Key Design Decisions:** 3-pane authoring workspace mirroring the mental model of modern LMS course builders; dedicated test-case configuration table with hidden/visible toggles.
- **Known Issues:** Branch is unmerged; complex UI state management is simulated with basic vanilla JS DOM manipulation; WYSIWYG editor is a plain textarea mockup.
- **Handoff Verdict:** **Preserve Layout / Review UI Complexity**. The three-pane authoring layout is comprehensive and directly addresses curriculum requirements.

#### SCR-06 — Faculty Grading & Monitoring
- **Purpose:** Assessment evaluation workspace allowing faculty to filter submissions by course/task/status, view submitted code/queries, review automated test case execution logs, assign manual rubric scores, write qualitative feedback, and monitor cohort completion analytics.
- **Intended Role:** Faculty.
- **Location:** `prototypes/scr-06-faculty-grading/index.html` (Branch: `prototype/faculty-admin-ui`).
- **Current State:** Prototype complete on topic branch. Features split-screen view: left submission roster with status indicators, center student work/diff viewer, and right grading rubric/feedback pane.
- **Key Design Decisions:** Two-column split review layout enabling rapid submission cycling via Next/Prev shortcuts; clear visual separation between auto-grade score and manual overrides.
- **Known Issues:** Branch is unmerged; cohort analytics charts are static placeholder cards.
- **Handoff Verdict:** **Preserve Structure / Polish Grading Controls**.

#### SCR-07 — Admin Platform Console
- **Purpose:** System-level governance dashboard allowing administrators to manage user accounts, assign system roles (RBAC), provision courses, monitor server status metrics, and view system logs.
- **Intended Role:** Administrator.
- **Location:** `prototypes/scr-07-admin-console/index.html` (Branch: `prototype/faculty-admin-ui`).
- **Current State:** Prototype complete on topic branch with refinements (`refined-v1.png`). Features classic administrative dashboard with left sidebar navigation, top metric summary cards, comprehensive user data table with filter dropdowns, and pagination controls.
- **Key Design Decisions:** High-density data table layout using subtle row dividers and colored status badges (`Active` = green, `Suspended` = yellow/red).
- **Known Issues:** Branch is unmerged; role permission editing modal is not modeled.
- **Handoff Verdict:** **Preserve Layout / Review Data Density**. Standard and robust admin layout.

---

## 8. UI Design State & Visual System

### 8.1 Current Design Tokens (`docs/ui-design/design-tokens.md`)

The current design system is built around a dark, technical "developer IDE" aesthetic:

| Token Name | Hex Value | Primary Tailwind Mapping | Semantic Role |
|---|---|---|---|
| **Canvas** | `#0A1128` | `bg-[#0A1128]` / `bg-canvas` | Main viewport & background layer |
| **Surface** | `#1C2541` | `bg-[#1C2541]` / `bg-surface` | Cards, navigation bars, panels, modals |
| **Border** | `#2A375A` | `border-[#2A375A]` / `border-borders`| Structural dividing lines, card outlines |
| **Primary** | `#00E5FF` | `text-[#00E5FF]` / `bg-[#00E5FF]` | Electric Cyan: primary CTAs, active nav items, key highlights |
| **Success** | `#00E676` | `text-[#00E676]` / `bg-[#00E676]` | Bright Mint: passing test cases, published status, completed steps |
| **Warning** | `#FFD600` | `text-[#FFD600]` / `bg-[#FFD600]` | Amber Yellow: pending review, warnings, audit notifications |
| **Text Primary** | `#F8F9FA` | `text-[#F8F9FA]` / `text-mainText` | Pure Off-White: high-contrast headers, active labels, body text |
| **Text Muted** | `#8D99AE` | `text-[#8D99AE]` / `text-mutedText`| Slate Gray: secondary descriptions, timestamps, inactive icons |

### 8.2 Typography & Layout Conventions
- **Sans-serif Font:** Inter / system UI fallback (`ui-sans-serif, system-ui, sans-serif`) for general interface, dashboard metrics, and navigation.
- **Monospace Font:** JetBrains Mono / SFMono / Menlo (`ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas`) for code editors, SQL queries, and terminal output.
- **Scrollbar Styling:** Custom webkit scrollbars (8px width, `#0A1128` track, `#2A375A` thumb with `#8D99AE` hover).
- **Layout Model:** Fixed viewport height (`h-screen overflow-hidden` or `overflow-y-auto`) with multi-pane CSS Grid or Flexbox columns.

### 8.3 Visual Inconsistencies & Technical Audit
During the prototype audit across branches, several visual inconsistencies were identified:
1. **Font Awesome Dependency:** Some prototypes (`scr-07`, `scr-01`) reference external Font Awesome CDN icons (`<i class="fas fa-edit"></i>`), whereas `scr-02` and `scr-03` use inline SVG icons. The production system should standardize on a single SVG icon library (e.g., Lucide React).
2. **Color Token Naming Divergence:** In `scr-02` and `scr-03`, Tailwind configuration defines `mainText` and `mutedText`. In `scr-07`, the config defines `light` and `muted`. This must be normalized into a unified Tailwind theme config.
3. **Contrast and Hierarchy:** The `#8D99AE` muted text on `#1C2541` surface occasionally falls below WCAG AAA contrast for small text (11px–12px). Claude should evaluate subtle contrast adjustments.
4. **Hardcoded Heights vs. Flex-1:** Several prototypes use hardcoded pixel heights (`h-14`, `h-16`) mixed with arbitrary calculations. In React, these should use consistent layout wrappers.

---

## 9. Database Design & Data Architecture

### 9.1 Microsoft SQL Server Schema Overview (`docs/database/database-design.md`)

The database design provides a 15-entity relational schema mapped directly to the 5 Level 1 DFD Data Stores:

```text
D1: User Data
  ├── Roles (RoleId, RoleName, Description)
  └── Users (UserId, RoleId, Name, Email, PasswordHash, Status, LastLogin, CreatedAt)

D2: Course Content
  ├── Subjects (SubjectId, Title, Description, CreatedAt)
  ├── SubjectEnrollments (EnrollmentId, UserId, SubjectId, EnrollmentType, EnrolledAt)
  ├── Topics (TopicId, SubjectId, Title, OrderIndex, IsPublished)
  └── Lessons (LessonId, TopicId, Title, ContentBody, Objectives, OrderIndex)

D3: Assessment Data
  ├── Assessments (AssessmentId, TopicId, Title, Type, Instructions, TargetLanguage, StarterCode, MaxScore, TimeLimitMs, MemoryLimitMb)
  ├── QuizQuestions (QuestionId, AssessmentId, QuestionText, QuestionType, Explanation)
  ├── QuizOptions (OptionId, QuestionId, OptionText, IsCorrect)
  └── TestCases (TestCaseId, AssessmentId, InputData, ExpectedOutput, IsHidden)

D4: Submission Data
  ├── Submissions (SubmissionId, StudentId, AssessmentId, SubmittedCode, Status, AutoGradeScore, FinalScore, Feedback, GradedBy, SubmittedAt)
  ├── SubmissionAnswers (AnswerId, SubmissionId, QuestionId, SelectedOptionId, TextResponse)
  └── TestCaseResults (ResultId, SubmissionId, TestCaseId, Passed, ActualOutput, ExecutionTimeMs)

D5: Analytics Data
  ├── StudentProgress (ProgressId, StudentId, TopicId, CompletionPct, LastAccessedAt)
  └── AILogs (LogId, StudentId, TopicId, LessonId, AssessmentId, Query, Response, Timestamp)
```

### 9.2 Key Relational Rules & Constraints
- **Role Enforcement:** `Users.RoleId` references `Roles.RoleId`. Foreign key constraints prevent orphaned accounts.
- **Hierarchical Cascade:** `Subjects` $\to$ `Topics` $\to$ `Lessons` / `Assessments`.
- **Assessment Polymorphism:** `Assessments.Type` is constrained to `'Quiz'` or `'Practical'`.
  - If `'Quiz'`: Related records reside in `QuizQuestions` and `QuizOptions`.
  - If `'Practical'`: Related records reside in `TestCases`, and code templates in `StarterCode`.
- **Submission Distinction:** `Submissions.SubmittedCode` holds practical C/C++ source code or SQL queries. Quiz submissions store option selections in `SubmissionAnswers`.

### 9.3 CRITICAL SECURITY GUARDRAIL: Isolated SQL Sandbox

> [!CAUTION]
> **STUDENT SQL EXECUTION MUST NEVER TOUCH THE APPLICATION DATABASE.**
> The Synora application database (`Users`, `Assessments`, `Submissions`, etc.) must be physically and logically isolated from the student SQL practice environment.
> 
> Under no circumstances may student queries (`SELECT`, `INSERT`, `DROP`, `UPDATE`) execute against the Synora Microsoft SQL Server instance.
> 
> **Architecture Requirement:**
> Student SQL practice must execute in an ephemeral, containerized database instance (or dedicated scratch database with read-only sandbox credentials, table resets, and strict CPU/memory limits).

---

## 10. GitHub & Development Workflow

### 10.1 Repository Identity & Governance
- **GitHub Repository:** [`NEC-08240/Synora`](https://github.com/NEC-08240/Synora)
- **Branch Protection:** The `main` branch is protected. Direct pushes to `main` are rejected. All work enters `main` exclusively through peer-reviewed Pull Requests.

### 10.2 Standard Development Lifecycle
$$\text{Issue} \longrightarrow \text{Branch} \longrightarrow \text{Commits} \longrightarrow \text{Pull Request} \longrightarrow \text{Peer Review} \longrightarrow \text{Merge}$$

### 10.3 Branch Naming Conventions
As codified in `CONTRIBUTING.md`:
- `feature/<name>` — New feature implementation (e.g., `feature/auth-jwt-service`)
- `fix/<name>` — Defect and bug fixes
- `docs/<name>` — Documentation additions or revisions (e.g., `docs/database-design`)
- `prototype/<name>` — UI/UX prototype development (e.g., `prototype/faculty-admin-ui`)
- `chore/<name>` — Build tools, configuration, repository hygiene

### 10.4 PR Review & Merge Standards (`docs/github/pr-review-and-merge.md`)
Every Pull Request requires:
1. Completion of `.github/pull_request_template.md` checklist.
2. Formal reviewer approval comment using the approved format:
   ```markdown
   ## Review Result
   - [x] Approved
   ### Comments
   Reviewed changes against approved Synora scope, documentation, and design requirements.
   ```
3. Structured merge commit message detailing included changes.

---

## 11. Antigravity's Historical Role & Execution Baseline

### 11.1 Work Performed to Date
Antigravity (powered by Gemini) has acted as the sole execution and development agent across all initial commits:
- Repository scaffolding, `.gitignore`, and contribution guides.
- GitHub issue templates and PR review standard documentation.
- Page inventory, initial design tokens, and ASCII wireframes.
- Static HTML + Tailwind CSS prototyping for SCR-01 through SCR-07.
- Visual verification using browser subagent tooling and screenshot capture.
- Level 1 and Level 2 DFD academic documentation and Microsoft SQL Server Phase 2 schema design.

### 11.2 Operational Strengths & Lessons Learned
- **High-speed execution:** Rapid file generation, structural scaffolding, and command execution in Windows PowerShell environments.
- **Visual verification capability:** Browser subagent captures pixel-exact screenshots for verification without manual operator intervention.
- **Boundary discipline:** Reliably preserves locked scopes when guardrails are documented.

### 11.3 Transition to Execution/DevOps
Antigravity is not designed to be the permanent sole architecture decision-maker for complex systems. Antigravity now transitions to being Claude's **hands**:
- Running shell commands, git operations, and local dev servers.
- Applying code changes directed by Claude's plans.
- Executing browser verification and taking screenshots.
- Managing branches, PR creation, and CI/CD operations.

---

## 12. Claude's New Role as Primary Engineering Brain

### 12.1 Division of Responsibilities

```text
+-----------------------------------------------------------------------------------+
|                        CLAUDE (Primary Engineering Brain)                         |
|  - System Architecture & API Design       - UI/UX Design Reasoning & Design System|
|  - Technical Decision-Making              - Code Review & Security Audit          |
|  - Complex Bug Diagnosis                  - Obsidian Second Brain Knowledge Mgmt  |
+-----------------------------------------------------------------------------------+
                                         |
                       Task Directives & Implementation Plans
                                         v
+-----------------------------------------------------------------------------------+
|                       ANTIGRAVITY (Execution & DevOps Agent)                      |
|  - Workspace File Edits & Creation        - Browser Automation & Screenshots      |
|  - Git Branching, Commits, PR Operations  - Local Dev Server Execution            |
|  - Test Runner & CLI Execution            - Environment Health & Scratch Scripts  |
+-----------------------------------------------------------------------------------+
```

### 12.2 Model Routing Strategy for Claude

To balance reasoning depth with operational efficiency, Claude should be deployed across three tiers:

```text
┌─────────────────┬─────────────────────────────────────────────────────────────────┐
│ Model           │ Target Responsibilities                                         │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ **Claude Opus** │ - High-complexity system architecture & data modeling           │
│                 │ - Fundamental UI/UX design overhaul & visual language redesign  │
│                 │ - Security threat modeling (sandbox escape prevention, RBAC)    │
│                 │ - Critical architectural dispute resolution                     │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ **Claude Sonnet**│ - Structured implementation planning & step-by-step sequencing │
│                 │ - Component-level technical design (React props, state hooks)   │
│                 │ - REST API endpoint contracts & WebSocket framing specs         │
│                 │ - Code review of Antigravity implementations                    │
│                 │ - Testing strategy & test case design                           │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ **Claude Haiku**│ - Routine documentation updates & changelog synchronization     │
│                 │ - Mechanical Obsidian note updates & link verification          │
│                 │ - Simple lint error fixes & minor script adjustments            │
└─────────────────┴─────────────────────────────────────────────────────────────────┘
```

---

## 13. Obsidian Second Brain Integration

### 13.1 Vault Environment
The user maintains a local-first knowledge management system named **Personal Observatory** (Vault ID: `observatory`) powered by Obsidian.

### 13.2 Vault Conventions & Rules for AI Agents
1. **Always search before creating:** Run vault search queries (`obsidian_search_vault`) before writing new notes to avoid duplicate knowledge.
2. **Strict Folder Taxonomy:**
   - `00 - Command Center/`: Core navigation and vault indexes (`Second Brain Core.md`).
   - `02 - Projects/`: High-level project hub notes (`[[Projects Hub]]`, `[[CIPHER]]`, `[[OfflineTool]]`).
   - `03 - Knowledge/`: In-depth technical topics and agent handoffs (`[[CIPHER - Agent Handoff]]`, `[[Artificial Intelligence]]`, `[[Programming]]`).
   - `04 - Research/`: Open-ended research queries and investigations.
   - `05 - Daily Notes/`: Ephemeral logs and session notes.
3. **Wikilinking Integrity:** Always use valid `[[Note Name]]` syntax. **Never manufacture wikilinks to nonexistent notes.**
4. **No Terminal Dumps or Secrets:** Do not log transient CLI output, raw stack traces, API keys, or credentials into Obsidian.
5. **Preserve User Knowledge:** Never overwrite or delete user notes without explicit instruction.

### 13.3 Existing Synora Notes State
Prior to this handoff, **no Synora notes existed in the vault**. As part of this handoff deliverable:
- `02 - Projects/Synora.md` is created as the primary project note.
- `03 - Knowledge/Synora - Agent Handoff.md` is created as the dedicated technical handoff note.
- `02 - Projects/Projects Hub.md` is updated to include `[[Synora]]`.

---

## 14. Important Git History & Milestones

The following table summarizes all meaningful milestones across the Git history:

| Commit / PR | Branch | Key Milestone / Contribution |
|---|---|---|
| `d7b8fc0` / `03f8dfe` | `main` | Initial repository creation and initial README.md. |
| `3a01727` (PR #1) | `main` | Merged comprehensive README outlining project scope, 5 modules, and team context. |
| `3063e86` (PR #2) | `main` | Merged standardized `.gitignore` for Node/React/IDE artifacts. |
| `d5bae41` (PR #3) | `main` | Merged `CONTRIBUTING.md` establishing branch and PR conventions. |
| `5426600` (PR #4) | `main` | Merged GitHub issue templates and `pull_request_template.md`. |
| `c594a3b`–`5905e0d` | `prototype/ui-design`| Added Phase 2 design docs: `page-inventory.md`, `design-tokens.md`, and `wireframes.md`. |
| `f47eed6`–`85d442c` | `prototype/ui-design`| Implemented SCR-02, SCR-03, and SCR-04 static prototypes with initial screenshots. |
| `b489435` (PR #5) | `main` | Merged `prototype/ui-design` into `main`, locking Phase 2 student UI baseline. |
| `1c2ac94` | `docs/pr-review-merge-format`| Codified peer review standard in `docs/github/pr-review-and-merge.md`. |
| `c8708b5` (PR #6) | `main` | Merged PR review standards into `main` (current head of `main`). |
| `a928db3` | `docs/database-design` | **Active Branch:** Implemented complete 15-entity Microsoft SQL Server schema doc. |
| `0a31863`–`d5e17b7` | `prototype/faculty-admin-ui` | **Active Branch:** Implemented SCR-01, SCR-05, SCR-06, SCR-07 prototypes and refined screenshots. |

---

## 15. Current Problems, Technical Debt & Divergence

The following items are incomplete, fragile, or require reconciliation:

### 15.1 Branch Divergence (Critical)
The repository currently has **two parallel topic branches** that both branched off `c8708b5` and have not been merged:
1. `docs/database-design` contains the SQL Server database design.
2. `prototype/faculty-admin-ui` contains the faculty, admin, and authentication prototypes.
Neither branch contains the other's work. They must be merged to `main` via PRs in a clean, sequential manner.

### 15.2 Documentation Inconsistencies
- `README.md` on `main` still states `Database: PostgreSQL`. This directly contradicts `docs/database/database-design.md`, which establishes Microsoft SQL Server as the locked choice.
- `Synora_DFD.docx` (untracked) only details Level 2 diagrams for Processes 1.0, 2.0, and 3.0. Level 2 diagrams for 4.0 (Faculty & Course Management) and 5.0 (Analytics & Recommendations) are missing.

### 15.3 Untracked Binary Artifacts
`Hand_Drawable_Level1_DFD.png` and `Synora_DFD.docx` are sitting untracked in the working tree. They should either be committed to a formal `docs/architecture/` folder or tracked properly.

### 15.4 Prototype Limitations (Not Production Code)
- Prototypes use the Tailwind CDN script (`cdn.tailwindcss.com`), which is unsupported for production builds.
- All state, editor content, and student scores are hardcoded JavaScript mocks.
- No real syntax highlighting library (e.g., Prism.js, Monaco, or CodeMirror) is integrated; code areas are simple `<pre>` or `<textarea>` tags.
- Iconography is mixed between inline SVG and external Font Awesome classes.

### 15.5 Missing Technical Specifications
- **No REST API Specification:** Endpoint routes (e.g., `/api/v1/auth/login`, `/api/v1/submissions`) and request/response JSON schemas have not been specified.
- **No WebSocket Protocol Contract:** The payload structure for streaming audio and text between the client, Node.js backend, and Gemini Live API has not been defined.
- **No Sandbox Interface Contract:** How Node.js communicates with the execution sandbox (gRPC, REST, or Docker CLI invocation) has not been specified.

---

## 16. UI/UX Redesign Guidance for Claude

The immediate next design phase is a **comprehensive visual system audit and redesign pass led by Claude**.

### 16.1 Design Intent of the Current Baseline
The initial design was created to establish a dark, immersive "developer IDE" atmosphere (`#0A1128` canvas, `#1C2541` surface, `#00E5FF` electric cyan accents). It aimed to make student learning feel serious, modern, and aligned with professional coding tools rather than a generic corporate LMS.

### 16.2 Successful Elements to Preserve
- **Three-Pane Learning Workspace (SCR-03):** The layout of Content (Left) + Code/Output (Center) + AI Companion (Right) is universally praised by the team and aligns with the core workflow.
- **Role-Aware Unified Entry (SCR-01):** Single login gateway avoiding confusing multi-tab login screens.
- **Two-Column Review Workspace (SCR-06):** Submission roster on the left and full-screen code/rubric view on the right maximizes grading efficiency.

### 16.3 Areas Demanding Claude's Improvement
- **Visual Sophistication & Depth:** The current palettes use flat borders (`#2A375A`) and solid backgrounds. Claude should introduce subtle surface gradients, refined border opacities, glassmorphism accents where appropriate, and better elevation hierarchy.
- **Typography & Font Scaling:** Standardize on Inter or Outfit for UI text with a strict mathematical type scale, and JetBrains Mono for technical content.
- **Interactive States & Micro-interactions:** Add smooth transition tokens for hover states, focus rings, active tabs, and drawer expansions.
- **Shared Design System Extraction:** Before building React components in Phase 3, extract reusable design tokens into a central theme:
  - Button hierarchy (Primary Cyan, Secondary Surface, Danger/Muted)
  - Card containers & panel headers
  - Code editor chrome & status pills
  - Badges (Status, Language, Role)
  - Form inputs and focus borders

---

## 17. Actionable Roadmap & Next Steps

```text
  Phase 2 Reconciliation           Claude UI/UX Redesign Pass          Phase 3 Engineering Setup
┌─────────────────────────┐      ┌─────────────────────────┐      ┌─────────────────────────┐
│ 1. Open PR for          │      │ 3. Claude Design Audit  │      │ 5. Bootstrap Vite/React │
│    docs/database-design │ ───> │    & Token Refinement   │ ───> │    & Node.js Express    │
│ 2. Open PR for          │      │ 4. Update Design Tokens │      │ 6. Implement Schema DDL │
│    faculty-admin-ui     │      │    & Screen Specs       │      │    on SQL Server        │
└─────────────────────────┘      └─────────────────────────┘      └─────────────────────────┘
```

### 17.1 Immediate Next Steps (Phase 2 Closeout)
1. **Reconcile Branch Divergence:**
   - Review and merge `docs/database-design` into `main` via PR.
   - Review and merge `prototype/faculty-admin-ui` into `main` via PR.
   - Update `README.md` to reflect Microsoft SQL Server as the locked database.
2. **Commit or Relocate Untracked DFD Assets:**
   - Move `Hand_Drawable_Level1_DFD.png` and `Synora_DFD.docx` into `docs/architecture/` and commit them.
3. **Claude UI/UX Design Audit:**
   - Claude performs a comprehensive review of the 7 screens.
   - Deliver refined design tokens and screen specifications in `docs/ui-design/`.

### 17.2 Near-Term Steps (Phase 2 to Phase 3 Bridge)
1. **Technical Specifications:**
   - Author REST API endpoint contract (`docs/technical/api-spec.md`).
   - Author WebSocket streaming protocol specification for Gemini Live AI tutor.
   - Define execution sandbox architecture and isolated student SQL environment.
2. **Phase 2 Design Lock:**
   - Conduct team design review and formally lock Phase 2 deliverables.

### 17.3 Future Phase Steps (Phase 3 Incremental Development)
1. **Scaffold Production Repositories:**
   - Initialize `/frontend` (React + Vite + Tailwind CSS + plain JS).
   - Initialize `/backend` (Node.js + Express + JWT auth).
2. **Database Provisioning:**
   - Write and execute T-SQL DDL migration scripts for Microsoft SQL Server.
3. **Implement Module 1 (Auth & Interactive Learning Workspace).**

---

## 18. Core Handoff Principles

All engineering work conducted on the Synora project must adhere to these twelve immutable principles:

1. **Preserve Verified Project Decisions:** Never re-litigate decisions already locked (e.g., MSSQL choice, plain JS, 3 subjects, 3 roles) without explicit user authorization.
2. **Do Not Silently Expand Scope:** The V1 scope is locked. Guardrails against custom LLM training, custom compilers, dynamic ML recommenders, and extra subjects must be strictly enforced.
3. **Do Not Assume Prototypes Are Production Code:** The current HTML/Tailwind files are visual references and structural prototypes, not production application code.
4. **Do Not Claim Unfinished Work Is Complete:** Be transparent about gaps, missing tests, unmerged branches, and mocked interactions.
5. **Distinguish Requirements from Proposals:** Clearly separate what is formally agreed upon in the SRS/Design from exploratory suggestions.
6. **Claude Owns Engineering Reasoning:** System architecture, design decisions, data modeling, code review, and technical strategy belong to Claude.
7. **Antigravity Owns Repository Execution:** File operations, terminal commands, test execution, browser automation, and DevOps tasks belong to Antigravity.
8. **The Project Owner Owns Major Decisions:** Pivot points, scope alterations, and external submissions remain under the human project owner's authority.
9. **Obsidian is Persistent Project Memory:** Store durable architectural findings, decisions, and handoff context in the user's Second Brain vault using clean, verified wikilinks.
10. **GitHub Remains the Source of Truth:** Uncommitted or unmerged local code is not canon; the GitHub repository state dictates verified progress.
11. **Documentation Must Reflect Reality:** If code or architecture changes, update corresponding documentation in the same cycle.
12. **When Uncertain, Identify the Uncertainty:** Never guess or hallucinate requirements. Explicitly label unknowns as uncertain and solicit clarification.

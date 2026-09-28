# Design Proposal: Synora V1 SCR-05 - Faculty Authoring Studio

## 1. Overall Page Composition
The Faculty Authoring Studio (SCR-05) requires a layout that maximizes the workspace for content creation while keeping structural navigation readily accessible. The proposed composition is a multi-pane layout, which is standard for complex authoring environments (like IDEs or advanced CMS).

*   **Top Bar (Global Navigation & Context):** Branding, global faculty tools, user profile, and breadcrumb navigation indicating the current authoring context (e.g., *Subject > Topic > Lesson*).
*   **Left Sidebar (Structural Hierarchy):** A collapsible tree-view navigation for managing the Course/Subject structure.
*   **Main Content Area (Authoring Canvas):** The central and largest pane where the actual authoring happens. Its content changes based on what is selected in the Left Sidebar.
*   **Right Sidebar (Contextual Settings & Actions):** A secondary sidebar (collapsible) that shows metadata, settings, and publishing controls for the currently selected item in the main canvas.

*Why this composition?* It allows faculty to maintain mental context of where they are in the curriculum (left), focus on the detailed content (center), and manage metadata/publishing states (right) without constantly switching screens.

## 2. Navigation Structure
*   **Global Navigation (Top Bar):** Minimal to avoid distraction. Includes links back to the Faculty Dashboard, a "Preview Course" button, and standard profile/settings dropdown.
*   **Breadcrumbs:** Essential for deep hierarchies. E.g., `Data Structures in C` > `Arrays` > `Multi-dimensional Arrays`.
*   **Primary Navigation (Left Sidebar):** This is the core navigation for authoring. It acts as an interactive outliner.

## 3. Subject → Topic → Lesson Hierarchy (Left Sidebar)
The left sidebar will feature a nested, drag-and-drop enabled tree view.
*   **Level 1: Subjects** (e.g., C Programming, DBMS)
*   **Level 2: Topics** (e.g., Pointers, SQL Joins)
*   **Level 3: Items** (Lessons, Quizzes, Practical Tasks)

**UI Details:**
*   Use collapsible carets for Subjects and Topics.
*   Icons to differentiate content types (e.g., 📄 for Lesson, ❓ for Quiz, 💻 for Practical Task).
*   A persistent "+ Add Content" button at the bottom of the sidebar or inline hover actions to add items directly within a specific topic.
*   *Color tokens:* Background `Surface: #1C2541`, Borders `Borders: #2A375A`. Selected item highlighted with a subtle `Primary/Cyan: #00E5FF` left border or background tint.

## 4. Lesson Authoring Area (Main Canvas)
When a "Lesson" is selected, the main canvas becomes a rich text / block editor.
*   **Header:** Title input field (large typography) and a brief description field.
*   **Editor:** A block-based WYSIWYG editor (conceptually similar to Notion or Gutenberg) allowing faculty to add:
    *   Text paragraphs, headings, lists.
    *   Code blocks (with syntax highlighting matching the dark theme).
    *   Inline alerts/callouts (using `Success`, `Warning` tokens).
*   *Color tokens:* Background `Canvas: #0A1128`, Text `Light text: #F8F9FA`. Input fields use `Surface: #1C2541`.

## 5. Learning Objectives (Right Sidebar)
Learning objectives are tied to the specific lesson or topic being authored.
*   Located in a dedicated tab or section within the Right Sidebar.
*   Simple UI: A list of current objectives with a "Delete" icon, and an input field with an "Add" button to append new ones.
*   *Why Right Sidebar?* Objectives are metadata that guide the authoring, not the content itself. Keeping them visible alongside the editor ensures alignment.

## 6. Resources (Right Sidebar)
*   Also located in the Right Sidebar (perhaps as an accordion panel below Learning Objectives).
*   Allows faculty to attach supplementary materials (PDFs, links, slides) to the current lesson.
*   UI: Drag-and-drop upload zone or URL input field.

## 7. Quiz Creation (Main Canvas)
When a "Quiz" is selected in the hierarchy, the main canvas changes to a quiz builder.
*   **Header:** Quiz Title and configuration (e.g., Time Limit, Passing Score).
*   **Question List:** A vertical list of created questions. Each question is a card (`Surface: #1C2541`).
*   **Question Editor (Expanded Card):**
    *   Question text area.
    *   Question type selector (Multiple Choice, True/False, Multiple Answer).
    *   List of options with radio buttons/checkboxes to mark the correct answer.
    *   "Add Option" button.
    *   Explanation field (shown to students after answering).
*   **Controls:** "+ Add Question" button at the bottom.

## 8. Practical C/C++/SQL Task Creation (Main Canvas)
This is the core differentiator for Synora. When a "Practical Task" is selected, the main canvas is split vertically or uses a tabbed interface.
*   **Tab 1: Task Description:** Rich text editor for writing the problem statement, constraints, and input/output formats.
*   **Tab 2: Environment Setup:** Select language (C, C++, SQL), set time limits, and memory limits.
*   **Tab 3: Test Cases:** Crucial for automated grading (simulated in UI).
    *   List of test cases.
    *   Each test case has: Input data, Expected Output data, Visibility toggle (Hidden vs. Visible to student).
*   **Tab 4: Starter Code / Solution:** Code editor component to provide the initial boilerplate to the student and to write the reference solution.

## 9. Draft / Preview / Publish Controls (Top Bar & Right Sidebar)
*   **Status Indicator:** Prominent badge indicating current state (e.g., `Draft` in `Warning: #FFD600` or `Muted text: #8D99AE`, `Published` in `Success: #00E676`).
*   **Top Bar Actions:**
    *   "Preview" button (opens a modal or new tab showing how the student sees it).
    *   "Save Draft" button.
    *   Primary "Publish" button (uses `Primary/Cyan: #00E5FF`).

## 10. Faculty Workflow
1.  **Structure:** Faculty creates a Subject, adds Topics, and skeletons out empty Lessons/Tasks in the Left Sidebar.
2.  **Drafting:** Faculty clicks into an empty item, writes the content in the Main Canvas, and adds metadata in the Right Sidebar.
3.  **Refining:** Adds quizzes and practical coding tasks, defining test cases carefully.
4.  **Preview & Publish:** Previews the module from a student's perspective, then clicks Publish to make it live.

## 11. Important UI States
*   **Empty States:** When a new Subject is created, the main canvas should have a welcoming empty state guiding them to "Create your first Topic".
*   **Unsaved Changes:** A visual indicator (e.g., an asterisk or "Unsaved" text) near the title or in the top bar.
*   **Validation Errors:** If a coding task lacks test cases or a quiz lacks a correct answer, highlight the missing requirement in `Warning: #FFD600` or a distinct error color if we decide to introduce one, preventing publishing.

## 12. Responsive Behavior
*   **1920×1080 (Large Desktop):** All three panes (Left Sidebar, Main Canvas, Right Sidebar) are fully expanded and visible simultaneously. Ample breathing room.
*   **1366×768 (Standard Laptop):** The Left Sidebar and Right Sidebar should be easily collapsible (via hamburger menu or toggle icons) to maximize the Main Canvas width. The Right Sidebar might default to closed, opening as a drawer overlay when settings are clicked.
*   **Mobile/Tablet:** (Lower priority for authoring, but if considered) Left sidebar becomes an off-canvas drawer. Right sidebar becomes a bottom sheet or a separate tab in the main view.

## 13. Relationship to Existing Synora Screens
*   **Visual Consistency:** Uses the identical color palette (`#0A1128`, `#1C2541`, etc.) to feel cohesive with SCR-02 (Dashboard) and SCR-04 (Coding Environment).
*   **Component Reuse:** The code editor component used in SCR-04 will be reused in the Practical Task Creation view. The button styles, card structures (`Surface: #1C2541`), and typography should be identical.
*   **Contextual Shift:** While SCR-02 is about consumption/metrics, SCR-05 is about creation. The layout shifts from dashboard widgets to an IDE-like three-pane setup to support deep focus.

## 14. UX Concerns or Recommendations
*   **Auto-save is critical.** Losing complex coding tasks or long lesson text due to a browser crash is catastrophic for faculty trust. The UI must clearly communicate "Saved just now".
*   **Complexity Management:** The Practical Task creation is complex. Consider a wizard or step-by-step approach instead of a massive single form if usability testing shows faculty are overwhelmed.
*   **Bulk Actions:** Faculty might need to reorder topics or bulk publish lessons. The tree view needs to support drag-and-drop reordering robustly.

---

## Implementation Notes for Tomorrow
*   **Layout Structure:** Start by creating a CSS Grid layout with three main columns: `250px` (Left Sidebar), `1fr` (Main Canvas), `300px` (Right Sidebar). Use Tailwind's grid utility classes (`grid grid-cols-[250px_1fr_300px]`).
*   **Colors:** Define the provided hex codes in the `tailwind.config.js` file (if applicable) or use arbitrary values directly (e.g., `bg-[#0A1128]`). Apply `bg-[#0A1128]` to the `body` or main wrapper, and `bg-[#1C2541]` to sidebars and cards.
*   **Typography:** Use `text-[#F8F9FA]` as the default text color. Use `text-[#8D99AE]` for secondary information and labels.
*   **Borders:** Use `border-[#2A375A]` to separate the three main panes and to outline input fields.
*   **Interactive Elements:** Mock up standard Tailwind buttons for Publish (`bg-[#00E5FF] text-black`), Save Draft, and Add Content.
*   **Fake the Tree View:** For the static prototype, build the Left Sidebar using nested `ul`/`li` elements styled with Tailwind padding to represent hierarchy.
*   **Focus State:** Build the prototype showing the "Practical Task Creation" state in the Main Canvas, as it is the most complex and Synora-specific view.

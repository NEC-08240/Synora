# Design Proposal: Synora V1 SCR-06 - Faculty Grading & Monitoring

## 1. Overall Page Composition
A two-column layout optimized for review workflows. The left sidebar contains the list of students/submissions, and the main right pane displays the selected submission details, code, and grading tools.
*   **Top Bar:** Global navigation, context, and quick filters (e.g., "Pending Review", "Graded").
*   **Left Sidebar (Submission List):** A searchable, filterable list of student submissions for a specific task.
*   **Main Workspace (Review & Grading):** 
    *   Top: Student details, submission time, and auto-grade results.
    *   Middle: The student's submitted code/SQL and execution output.
    *   Bottom/Right Drawer: Manual grading rubric, point assignment, and feedback text area.

## 2. Faculty Navigation
*   Top bar includes links: Dashboard, Authoring (SCR-05), Grading (Active), Students.
*   Breadcrumbs: Course > Topic > Task > Student Name.

## 3. Submission/Student Filtering
*   Dropdowns in the left sidebar to filter by Subject, Task, and Status (Pending, Graded, Late).
*   Search bar for specific student names or IDs.

## 4. Submission List
*   Cards for each student.
*   Shows: Student Name, Avatar, Status (Indicator dot: warning for pending, success for graded), Auto-grade score (if applicable), and submission timestamp.

## 5. Selected Submission View
*   Header with Student Name, Task Title, and overall status.
*   Tabs or split view to see: 1. Student Code, 2. Test Case Results (Auto-grading details), 3. Plagiarism/Similarity report (mocked).

## 6. Student Submitted Work
*   Read-only code editor view matching the styling of SCR-04 (Monospace font, syntax highlighting).
*   Ability to expand/collapse code files if multiple exist.

## 7. Practical/Assessment Result Information
*   Clear visualization of passed vs. failed test cases (green checks, red crosses).
*   Execution time and memory usage metrics from the student's run.

## 8. Manual Grading Interface
*   A fixed panel or floating card next to the code view.
*   Input for "Points Awarded" out of "Total Points".
*   Optional rubric checklist (e.g., "Code Style", "Efficiency", "Correctness").

## 9. Feedback Area
*   Rich text area for the faculty member to write qualitative feedback.
*   "Return to Student" or "Publish Grade" button to finalize.

## 10. Student/Batch Progress Monitoring
*   A separate tab or high-level view showing a progress bar or simple chart of how many students have completed the current task vs. pending.

## 11. Important UI States
*   **Empty State:** When no submission is selected, prompt the user to select one from the left.
*   **Graded State:** Read-only view of the assigned grade with an "Edit Grade" button.

## 12. Responsive Behavior
*   **1920x1080 & 1366x768:** Standard split-pane view. Sidebar (300px), Main Content (remaining).
*   Smaller screens: Sidebar becomes a drawer or stacks vertically.

## 13. Relationship to Existing Synora Screens
*   Uses the same visual language (Canvas `#0A1128`, Surface `#1C2541`, Primary `#00E5FF`).
*   Reuses the Code Editor UI from SCR-04 and the layout structure of SCR-05.

## 14. UX Concerns
*   Faculty need to grade quickly. The interface must minimize clicks between submissions. "Next Submission" and "Previous Submission" buttons are critical.
*   Clear distinction between auto-graded points and manually overridden points.

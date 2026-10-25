# Design Proposal: Synora V1 SCR-07 - Admin Platform Console

## 1. Overall Page Composition
A classic dashboard layout designed for high data density and management.
*   **Top Bar:** Admin profile, global search, and system status indicators.
*   **Left Sidebar:** Fixed navigation for admin modules (Users, Roles, Subjects, Settings).
*   **Main Content Area:** Data tables, forms, and metric cards based on the selected module.

## 2. Admin Navigation
*   Sidebar items: Dashboard (Overview), User Management, Role Management, Course/Subject Management, System Settings.
*   Active state highlighted with `Primary/Cyan: #00E5FF`.

## 3. User Management
*   The primary view for the prototype.
*   A comprehensive data table listing all platform users.
*   Columns: Name, Email, Role, Status, Last Login, Actions.
*   "+ Add User" primary action button.

## 4. Role Management
*   (Conceptual for V1) UI to define permissions for Student vs. Faculty vs. Admin.
*   Shown as tags or badges in the user table.

## 5. Subject Management
*   High-level view of all courses on the platform, assigned faculty, and enrollment counts.

## 6. Platform Configuration
*   Global settings (e.g., Default Semester, Enrollment toggles).

## 7. Important Status/State Indicators
*   User status badges (Active in `Success: #00E676`, Suspended in `Warning: #FFD600` or red).
*   System health metrics (e.g., Active Users, Server Status) at the top of the dashboard.

## 8. Responsive Behavior
*   Standard collapse of the left sidebar into a hamburger menu on smaller screens.
*   Data tables should scroll horizontally on narrow displays to preserve layout.

## 9. Relationship to the Existing Synora Interface
*   Retains the dark theme (`#0A1128` canvas, `#1C2541` surface) to ensure brand consistency, but leans heavier into data tables and lists rather than IDE-like panels.

## 10. UX Concerns
*   Data tables must be easy to read. Alternate row colors or subtle borders (`#2A375A`) are essential.
*   Destructive actions (like "Delete User") must have clear confirmation modals.

# Design Proposal: Synora V1 SCR-01 - Auth & Gateway

## 1. Overall Composition
A centered, focused, single-column layout on a dark, immersive background. The goal is a distraction-free entry point.
*   **Background:** Deep canvas (`#0A1128`) potentially with subtle, abstract geometric or code-inspired background graphics (low opacity) to feel technical and premium.
*   **Center Card:** The main authentication container using `Surface: #1C2541` with a soft glow or shadow.

## 2. Synora Branding
*   Prominent logo placement at the top of the auth card or just above it.
*   Brand colors (Cyan `#00E5FF`) used for primary actions and focus states.

## 3. Login Form
*   Clean input fields: Email/Username and Password.
*   Inputs have a transparent background with `#2A375A` borders, lighting up with Cyan on focus.
*   "Remember me" checkbox and "Forgot Password?" link.
*   Large, full-width primary submit button: "Sign In".

## 4. Authentication Feedback States
*   **Loading:** Button shows a spinner, text changes to "Authenticating...".
*   **Error:** Invalid credentials show a subtle inline error message in red/warning (`#FFD600`), and input borders turn red.
*   **Success:** Button turns `Success: #00E676` briefly before redirecting.

## 5. Role-Aware Entry Concept
*   The system determines the role post-login, so there's no need for "Student Login" vs "Faculty Login" tabs. It's a unified gateway.
*   (Optional visual) A subtle text indicating "Unified Gateway for Students & Faculty".

## 6. Navigation/Entry Behavior
*   Post-login, users are routed automatically based on their backend role (to SCR-02 for students, SCR-05/06 for faculty, SCR-07 for admin).

## 7. Responsive Behavior
*   The center card scales down slightly on mobile, taking up nearly full width with some padding.
*   Background graphics adjust to remain subtle.

## 8. Relationship to the Other Synora Screens
*   Sets the tone for the dark, technical aesthetic used across all internal screens.
*   Uses the exact same typography (Inter) and token colors.

## 9. UX Concerns
*   Keyboard navigation is critical (Tab to move fields, Enter to submit).
*   Clear focus states for accessibility.
*   Avoid overwhelming the user with marketing fluff; keep it a pure utility gateway.

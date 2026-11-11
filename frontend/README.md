# Synora frontend

React 19 + Vite + Tailwind 4 + react-router. Plain JavaScript (JSX), no TypeScript.

## Run

1. Start the backend first (`backend/README.md`), listening on `http://localhost:4000`.
2. Then:
   ```bash
   cd frontend
   npm install
   npm run dev      # http://localhost:5173
   ```

Vite proxies `/api` (HTTP and WebSocket) to the backend, so the httpOnly `synora_token` cookie is
same-origin and no CORS setup is needed in development.

Other scripts: `npm test` (node:test), `npm run lint` (oxlint), `npm run build`.
Scripts call tools through `node node_modules/...` because the `&` in this repository's folder
path breaks npm's `.cmd` shims on Windows.

## Screens

| Route | Screen | Roles |
|---|---|---|
| `/login` | SCR-01 Auth & Gateway, role-based redirect | anyone |
| `/learn` | SCR-02 Student Learning Hub: allocated subjects, topics, lessons | Student |
| `/learn/lessons/:lessonId` | SCR-03 Workspace: lesson content, practice panel, AI tutor | Student |
| `/manage` | Read-only subject list (authoring UIs are scheduled for December) | Faculty, Administrator |

## Layout

- `src/api.js` fetch wrapper (`api`, `ApiError`) and `safeUrl`
- `src/auth.jsx` auth context, `RequireRole` route guard
- `src/pages/` one file per screen
- `src/components/` `Shell`, `PracticePanel` (C / C++ / SQL run), `TutorPanel` (AI relay chat)
- `src/index.css` design tokens from `docs/ui-design/design-tokens.md`

## Known limits

- The editor is a plain textarea. `shortcut:` no syntax highlighting; swap in CodeMirror if the review asks for it.
- Lesson content renders as plain text, not Markdown or HTML.
- The practice panel is a free scratchpad; it is not yet tied to activity tasks or submissions.
- The UI enforces nothing on its own: every permission check lives in the API.

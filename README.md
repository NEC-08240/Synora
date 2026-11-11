# Synora Live Smart Edification

Synora is a practice-oriented interactive learning platform designed to combine
learning, practical work, assessment, analytics, and recommendations in one
system.

## Project Overview

Synora is being developed as an academic project by a five-member team.
The platform focuses on learning and practicing:

- C
- C++
- DBMS / SQL

The system provides separate experiences for:

- Students
- Faculty
- Administrators

## Core Learning Workflow

Learn → Interact → Practice → Assess → Analyse → Recommend

## V1 Modules

1. Interactive Learning & Conversational AI
2. Practical Learning & Simulation
3. Assessment & Assignment
4. Faculty & Course Management
5. Learning Analytics & Rule-Based Recommendations

## Technology Stack

### Frontend
- React
- Vite
- JavaScript (ES6+)
- Tailwind CSS

### Backend
- Node.js
- Express.js

### Database
- Microsoft SQL Server

### Other Technologies
- WebSockets
- Docker
- Git / GitHub

## Project Structure

The repository will evolve incrementally according to the project
development phases.

```text
Synora/
├── docs/
├── prototypes/
├── frontend/
├── backend/
├── database/
└── .github/
```

## Running locally

Needs Node.js 22 or newer (developed on 24), SQL Server and, for C/C++ runs only, Docker.

1. **Database.** Run `database/schema.sql`, then `database/sandbox_setup.sql`, as a SQL Server administrator.
   Create the application login described in `backend/README.md`.
2. **Backend.**
   ```bash
   cd backend
   cp .env.example .env    # fill in DB_*, JWT_SECRET; SANDBOX_DB_* is needed for the SQL practice panel
   npm install
   npm run seed            # demo users, subjects, topics, lessons
   npm run dev             # http://localhost:4000
   ```
3. **Frontend.**
   ```bash
   cd frontend
   npm install
   npm run dev             # http://localhost:5173
   ```
4. Sign in with a demo account from `backend/README.md`.

Optional services, both off by default:

| Feature | Setting in `backend/.env` | Details |
|---|---|---|
| AI tutor | `GEMINI_API_KEY` | `docs/technical/ai-session-protocol.md` |
| C / C++ execution | `EXECUTOR_URL` (Piston runner) | `docs/technical/practice-execution.md` |

Checks: `npm test` in `backend/` and `frontend/`, and `npm run smoke` in `frontend/` with both servers running.

Project status and demo script: `docs/project/november-report.md`.

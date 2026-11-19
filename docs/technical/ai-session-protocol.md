# AI Tutor Session Protocol (Gemini Multimodal Live relay)

Module 1, Interactive Learning & Conversational AI. Implemented in `backend/src/ai/`.

## Why a relay

The Gemini Live API is a WebSocket authenticated with an API key. The key must never reach the
browser, so the browser talks to a Synora WebSocket and the Synora backend holds the only upstream
connection. The backend also enforces who may talk to the tutor (Students only) and never stores
what is said (locked decision: AI transcripts are not persisted, only an `AIQuery` event).

```
Browser ──(1) POST /api/v1/ai/sessions (cookie)──▶ Express ──INSERT LearningActivity(AIQuery)──▶ SQL Server
Browser ◀─(2) { sessionId, wsPath, available } ───┘
Browser ──(3) WS /api/v1/ai/ws?session=… (cookie)─▶ relay ──(4) wss://generativelanguage… ?key=GEMINI_API_KEY──▶ Gemini Live
Browser ◀─(5) { text delta } … { turn_complete } ──┘  ◀── serverContent ────────────────────────────────────────┘
```

## 1. Create a session

`POST /api/v1/ai/sessions` (Student). Body `{ lessonId? }`.
If a `lessonId` is given it must be a Published lesson in a subject allocated to the student's
batch (else `404`); its title, topic and objectives are folded into the system instruction so the
tutor knows what the student is reading.

Response `201`:

```json
{ "sessionId": "uuid", "wsPath": "/api/v1/ai/ws?session=uuid", "expiresAt": "…", "available": true,
  "context": { "lessonId": 3, "lessonTitle": "Pointers" } }
```

Sessions are in-memory, expire after 5 minutes if unused, and are **single-use**: the first upgrade
consumes them. `available: false` means `GEMINI_API_KEY` is not configured on the server; the UI
shows the tutor as unavailable instead of opening a socket.

## 2. WebSocket handshake

`GET /api/v1/ai/ws?session=<id>` with the normal `synora_token` cookie. The upgrade is refused with
`401` (no/invalid cookie, non-student) or `403` (unknown, expired, reused or foreign session,
disallowed `Origin`) or `429` (the student already has 2 live relay sockets). The 429 check runs
before the session is consumed, so a refused attempt leaves the session usable once a socket closes.

## 3. Frames (JSON text)

| Direction | Frame | Meaning |
|---|---|---|
| client → relay | `{ "type": "user_text", "text": "…" }` | One user turn, ≤ 4000 chars. Audio/video are not in V1. |
| relay → client | `{ "type": "ready" }` | Gemini accepted the setup; the client may send. |
| relay → client | `{ "type": "text", "delta": "…" }` | Streamed partial model text; append to the current reply. |
| relay → client | `{ "type": "turn_complete" }` | The model finished its reply. |
| relay → client | `{ "type": "error", "code", "message" }` | See codes below. Fatal codes are followed by a close. |

Error codes: `ai_unavailable` (no key configured, fatal), `upstream_error` (cannot reach Gemini,
fatal), `upstream_closed` (Gemini closed abnormally, e.g. quota or model name, fatal),
`not_ready` (sent before `ready`, non-fatal), `bad_message` (malformed frame, non-fatal).

Idle sockets are closed after 10 minutes. Closing the browser socket closes the upstream session.

## 4. Upstream mapping

- Setup frame: `{ setup: { model: "models/<GEMINI_MODEL>", generationConfig: { responseModalities: ["TEXT"] }, systemInstruction } }`.
- User turn: `{ clientContent: { turns: [{ role: "user", parts: [{ text }] }], turnComplete: true } }`.
- `serverContent.modelTurn.parts[].text` → `text` frames; `serverContent.turnComplete` → `turn_complete`.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | empty | From Google AI Studio. Empty = tutor reports unavailable. |
| `GEMINI_MODEL` | `gemini-2.0-flash-live-001` | Any Live-capable model id. |

## Frontend fallback behaviour

When `available` is false, or a fatal error frame arrives, the tutor panel shows the message, keeps
the lesson readable, and offers a Retry. Nothing is queued or stored.

## Verification status

Relay logic is covered by `backend/test/ai.test.js` against a Gemini-shaped fake upstream
(setup handshake, streamed deltas, key never reaching the client, auth/session rejections). Live
verification against Google requires a `GEMINI_API_KEY`, which was not available in this
environment; see the execution tracker.

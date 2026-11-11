/**
 * AI tutor sessions. The browser never sees the Gemini key: it asks for a session here,
 * then opens a WebSocket to our relay (relay.js) which talks to Gemini on its behalf.
 * Sessions live in memory (single API process) and are single-use.
 */
import { randomUUID } from 'node:crypto';
import { Router } from 'express';
import { config } from '../config.js';
import { query, queryOne } from '../db.js';
import { notFound, tooManyRequests } from '../http.js';
import { requireRole } from '../auth/middleware.js';
import { validate } from '../validate.js';

const sessions = new Map(); // sessionId -> { userId, systemInstruction, expiresAt }

export const WS_PATH = '/api/v1/ai/ws';

/** Single-use: returns the session only to its owner; a foreign or expired id leaves it intact. */
export function takeSession(sessionId, userId) {
  const session = sessions.get(sessionId);
  if (!session || session.userId !== userId || session.expiresAt < Date.now()) return null;
  sessions.delete(sessionId);
  return session;
}

function buildSystemInstruction(user, lesson) {
  const lines = [
    'You are Synora, a patient tutor for undergraduate students studying C, C++ and DBMS/SQL.',
    `The student's name is ${user.Name}.`,
    'Answer concisely, prefer worked examples, and ask a short check-question when it helps learning.',
    'Only help with C, C++, databases and SQL. Politely decline other topics.',
    'Do not write complete solutions to graded assignments; guide the student instead.',
  ];
  if (lesson) {
    lines.push(`The student is currently viewing the lesson "${lesson.Title}" in the topic "${lesson.TopicTitle}" (${lesson.SubjectTitle}).`);
    if (lesson.Objectives) lines.push(`Lesson objectives: ${lesson.Objectives}`);
  }
  return lines.join('\n');
}

export const aiRouter = Router();

aiRouter.post('/sessions', requireRole('Student'), async (req, res, next) => {
  try {
    const body = validate(req.body, { lessonId: { type: 'int', min: 1 } });
    let lesson = null;
    if (body.lessonId !== undefined) {
      // Same visibility rule as GET /lessons/:id — published and allocated to the student's batch.
      lesson = await queryOne(
        `SELECT l.LessonId, l.Title, l.Objectives, t.Title AS TopicTitle, s.Title AS SubjectTitle
           FROM dbo.Lessons l
           JOIN dbo.Topics t ON t.TopicId = l.TopicId
           JOIN dbo.Subjects s ON s.SubjectId = t.SubjectId
           JOIN dbo.FacultyAssignments fa ON fa.SubjectId = s.SubjectId AND fa.BatchId = @batchId
          WHERE l.LessonId = @lessonId AND l.Status = N'Published' AND t.Status = N'Published'`,
        { lessonId: body.lessonId, batchId: req.user.BatchId ?? -1 },
      );
      if (!lesson) return next(notFound('Lesson not found'));
    }
    const now = Date.now();
    let pending = 0;
    for (const [id, s] of sessions) {
      if (s.expiresAt < now) sessions.delete(id);
      else if (s.userId === req.user.UserId) pending += 1;
    }
    if (pending >= 5 || sessions.size > 1000) return next(tooManyRequests('Too many pending AI sessions, try again shortly'));

    const sessionId = randomUUID();
    const expiresAt = Date.now() + config.ai.sessionTtlSeconds * 1000;
    sessions.set(sessionId, { userId: req.user.UserId, systemInstruction: buildSystemInstruction(req.user, lesson), expiresAt });

    // Only the fact that an AI query happened is recorded, never the content (locked decision).
    await query(
      `INSERT INTO dbo.LearningActivity (StudentId, EventType, LessonId) VALUES (@studentId, N'AIQuery', @lessonId)`,
      { studentId: req.user.UserId, lessonId: body.lessonId ?? null },
    );

    res.status(201).json({
      sessionId,
      wsPath: `${WS_PATH}?session=${sessionId}`,
      expiresAt: new Date(expiresAt).toISOString(),
      available: Boolean(config.ai.apiKey),
      context: lesson ? { lessonId: lesson.LessonId, lessonTitle: lesson.Title } : null,
    });
  } catch (err) {
    next(err);
  }
});

import { Router } from 'express';

/*
 * Stub owned by M3-2 (student work and submit, endpoints 9-14). Declares ONLY its method+path pairs (no router.use middleware: this router is mounted ahead
 * of contentRouter on /api/v1, so any blanket middleware would run on every content request too).
 */
export const submissionsRouter = Router();

const notImplemented = (req, res) => res.status(501).json({ error: 'Not implemented' });

submissionsRouter.get('/activities/:id/draft', notImplemented);
submissionsRouter.put('/activities/:id/draft', notImplemented);
submissionsRouter.post('/activities/:id/submissions', notImplemented);
submissionsRouter.get('/activities/:id/submissions/mine', notImplemented);
submissionsRouter.get('/submissions/:id', notImplemented);
submissionsRouter.post('/activities/:id/events', notImplemented);

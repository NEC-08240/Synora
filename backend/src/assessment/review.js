import { Router } from 'express';

/*
 * Stub owned by M3-4 (faculty review, endpoints 15-17). Declares ONLY its method+path pairs (no router.use middleware: this router is mounted ahead
 * of contentRouter on /api/v1, so any blanket middleware would run on every content request too).
 */
export const reviewRouter = Router();

const notImplemented = (req, res) => res.status(501).json({ error: 'Not implemented' });

reviewRouter.get('/activities/:id/submissions', notImplemented);
reviewRouter.patch('/submissions/:id/grade', notImplemented);
reviewRouter.get('/submissions/:id/results', notImplemented);

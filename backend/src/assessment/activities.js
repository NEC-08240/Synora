import { Router } from 'express';

/*
 * Stub owned by M3-1 (authoring, endpoints 1-8). Declares ONLY its method+path pairs (no router.use middleware: this router is mounted ahead
 * of contentRouter on /api/v1, so any blanket middleware would run on every content request too).
 */
export const activitiesRouter = Router();

const notImplemented = (req, res) => res.status(501).json({ error: 'Not implemented' });

activitiesRouter.get('/topics/:topicId/activities', notImplemented);
activitiesRouter.post('/topics/:topicId/activities', notImplemented);
activitiesRouter.get('/activities/:id', notImplemented);
activitiesRouter.patch('/activities/:id', notImplemented);
activitiesRouter.post('/activities/:id/status', notImplemented);
activitiesRouter.put('/activities/:id/questions', notImplemented);
activitiesRouter.put('/activities/:id/test-cases', notImplemented);
activitiesRouter.put('/activities/:id/sql-spec', notImplemented);

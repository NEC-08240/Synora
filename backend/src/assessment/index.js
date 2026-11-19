import { Router } from 'express';
import { activitiesRouter } from './activities.js';
import { submissionsRouter } from './submissions.js';
import { reviewRouter } from './review.js';

// Spec section 4 names one assessmentRouter; sections 8's three files are composed here so app.js mounts it once.
export const assessmentRouter = Router();
assessmentRouter.use(activitiesRouter, submissionsRouter, reviewRouter);

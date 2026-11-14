// Pure state rules pulled out of components so node:test can cover them (no component test runner here).
export const SESSION_EXPIRED_MESSAGE = 'Your session has expired. Please sign in again.';

/** An error frame ends the current reply, so the idle-reply timer must stop and the chat must accept input again. */
export const stateAfterErrorFrame = (state) => (state === 'replying' ? 'ready' : state);

export const boundaryState = { ok: { failed: false }, crashed: { failed: true } };

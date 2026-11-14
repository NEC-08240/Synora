// Pure state rules pulled out of components so node:test can cover them (no component test runner here).
export const SESSION_EXPIRED_MESSAGE = 'Your session has expired. Please sign in again.';

/** An error frame ends the current reply, so the idle-reply timer must stop and the chat must accept input again; during connecting the connect timer is also stopped, so it must move to 'error' (retryable) instead of hanging. */
export const stateAfterErrorFrame = (state) => (state === 'replying' ? 'ready' : state === 'connecting' ? 'error' : state);

export const boundaryState = { ok: { failed: false }, crashed: { failed: true } };

import process from 'node:process';
import { createApp } from './app.js';
import { config } from './config.js';
import { getPool, closePool } from './db.js';
import { attachAiRelay } from './ai/relay.js';

const app = createApp();
await getPool(); // fail fast if the database is unreachable
const server = app.listen(config.port, () => console.log(`Synora API listening on http://localhost:${config.port}`));
attachAiRelay(server);
if (!config.ai.apiKey) console.warn('GEMINI_API_KEY not set: AI tutor will report itself unavailable');

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    server.close();
    await closePool();
    process.exit(0);
  });
}

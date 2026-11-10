import process from 'node:process';
import { createApp } from './app.js';
import { config } from './config.js';
import { getPool, closePool } from './db.js';

const app = createApp();
await getPool(); // fail fast if the database is unreachable
const server = app.listen(config.port, () => console.log(`Synora API listening on http://localhost:${config.port}`));

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    server.close();
    await closePool();
    process.exit(0);
  });
}

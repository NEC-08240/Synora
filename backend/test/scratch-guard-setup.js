// Loaded with `node --import` by the test and seed:test scripts, so it runs in every test file's process.
import process from 'node:process';
import { assertScratchDb } from './scratch-guard.js';

assertScratchDb(process.env);

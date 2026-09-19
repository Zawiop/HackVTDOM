import { createApp } from './app.js';
import { env, hasMapillary } from './config/env.js';

const app = createApp();

app.listen(env.port, () => {
  console.log(`[api] listening on http://localhost:${env.port}`);
  console.log(`[api] mapillary convenience layer: ${hasMapillary() ? 'enabled' : 'disabled (no token)'}`);
});

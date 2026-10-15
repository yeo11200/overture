import type { E2EConfig } from 'e2e';
import { web } from '@e2e-dev/web';

// Model-free suite: no agents, only screen/app/expect.
// E2E_CDP=http://127.0.0.1:9333 attaches to an already running Chrome instead
// of downloading Playwright's build (useful when the CDN download fails).
const cdp = process.env.E2E_CDP;

export default {
  tests: 'tests/**/*.e2e.ts',
  targets: [
    {
      engine: cdp ? web({ connect: { cdpEndpoint: () => cdp } }) : web(),
      app: {
        url: 'http://127.0.0.1:0',
        readyUrl: 'http://127.0.0.1:{port}/api/v1/unified/board',
        command: {
          executable: '.venv/bin/python',
          args: ['tests/e2e/unified_fixture.py', '--port', '{port}'],
          log: '.e2e/logs/app.log',
        },
      },
    },
  ],
} satisfies E2EConfig;

// Record the Overture demo video from sample data only.
//   node docs/demo/record.mjs            -> docs/demo/out/raw.webm
// Needs Google Chrome installed (Playwright launches it with channel "chrome").
import { spawn } from 'node:child_process';
import { readFileSync, mkdirSync, renameSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..', '..');
const out = join(here, 'out');
const port = 8799;
const base = `http://127.0.0.1:${port}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

mkdirSync(out, { recursive: true });
const server = spawn(join(repo, '.venv', 'bin', 'python'), [join(here, 'demo_server.py'), '--port', String(port)],
  { stdio: ['ignore', 'ignore', 'pipe'] });
const root = await new Promise((resolve, reject) => {
  let buf = '';
  server.stderr.on('data', (d) => {
    buf += d;
    const m = buf.match(/demo root: (\S+)/);
    if (m && buf.includes('unified board at')) resolve(m[1]);
  });
  server.on('exit', (code) => reject(new Error(`demo server exited ${code}\n${buf}`)));
});
const sessions = JSON.parse(readFileSync(join(root, 'sessions.json'), 'utf8'));

async function event(sid, name, extra = {}) {
  const s = sessions[sid];
  await fetch(`${base}/api/v1/unified/sessions/events?tool=${s.tool}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hook_event_name: name, session_id: sid, cwd: s.cwd, transcript_path: s.transcript, ...extra }),
  });
}

// Opening state: a busy morning across four projects.
await event('s-checkout', 'UserPromptSubmit', { prompt: '결제 페이지를 새 디자인 시스템으로 바꿔줘' });
await event('s-cart', 'Stop');
await event('s-units', 'UserPromptSubmit', { prompt: '금액을 minor units(정수)로 저장하도록 바꿔줘' });
await event('s-review', 'SessionStart');
await event('s-push', 'Stop');
await event('s-docs', 'UserPromptSubmit', { prompt: '새 엔드포인트 문서 추가' });
await sleep(3500); // let the mock Kanban agents pick up tickets

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  colorScheme: 'dark',
  recordVideo: { dir: out, size: { width: 1280, height: 900 } },
});
const page = await context.newPage();
await page.goto(base);
await page.waitForSelector('.gcard');
await sleep(2500);

// A reviewer asks for permission: the card turns purple, the tab counts it.
await event('s-review', 'UserPromptSubmit', { prompt: 'minor units 변환 코드를 리뷰하고 테스트 돌려줘' });
await sleep(1500);
await event('s-review', 'PermissionRequest', { tool_name: 'Bash', tool_input: { description: 'npm test' } });
await sleep(3000);

// Organise: roles, then one thread for the two payments agents.
const card = (sid) => page.locator(`.gcard[data-id="${sid}"]`);
await card('s-units').locator('select').selectOption('implement');
await sleep(900);
await card('s-review').locator('select').selectOption('review');
await sleep(1200);
for (const sid of ['s-units', 's-review']) {
  await card(sid).getByRole('button', { name: '+ 작업 줄기' }).click();
  await page.keyboard.type('minor units', { delay: 60 });
  await page.keyboard.press('Enter');
  await sleep(1400);
}
await sleep(1200);

// Hand-off arrow: implementation -> review.
const from = await card('s-units').locator('.gport').boundingBox();
const to = await card('s-review').boundingBox();
await page.mouse.move(from.x + 8, from.y + 8);
await page.mouse.down();
await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 25 });
await page.mouse.up();
await sleep(2500);

// Approved: review runs, implementation finishes.
await event('s-review', 'PreToolUse', { tool_name: 'Bash' });
await event('s-units', 'Stop');
await sleep(3000);

// Same data as a Kanban, then back to the chart.
await page.getByRole('tab', { name: '칸반' }).click();
await sleep(3500);
await page.getByRole('tab', { name: '차트' }).click();
await sleep(2500);

await context.close();
await browser.close();
server.kill('SIGTERM');
const video = readdirSync(out).find((f) => f.endsWith('.webm') && f !== 'raw.webm');
renameSync(join(out, video), join(out, 'raw.webm'));
console.log(join(out, 'raw.webm'));

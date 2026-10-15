import { describe, test } from '@e2e-dev/web';
import { expect } from 'e2e';

async function openKanban(app: { open(path?: string): Promise<void> }, screen: any) {
  await app.open('/');
  await screen.getByRole('tab', '칸반').tap();
}

async function post(baseUrl: string, path: string, body: unknown, method = 'POST') {
  const resp = await fetch(new URL(path, baseUrl), {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp;
}

describe('unified board', () => {
  test('shows tickets from every project on one board', async ({ app, screen }) => {
    await openKanban(app, screen);
    const todo = screen.getByRole('region', 'Todo');
    await expect(todo.getByText('로그인 버그 수정')).toBeVisible();
    await expect(todo.getByText('차트 추가')).toBeVisible();
    await expect(todo.getByText('캐시 튜닝')).toBeVisible();
    await expect(screen.getByText('alpha-app').first()).toBeVisible();
  });

  test('project chip filters its cards out and back in', async ({ app, screen }) => {
    await openKanban(app, screen);
    const chip = screen
      .getByRole('navigation', '프로젝트')
      .getByRole('button')
      .filter({ hasText: 'alpha-app' });
    await expect(screen.getByText('로그인 버그 수정')).toBeVisible();

    await chip.tap();
    await expect(screen.getByText('로그인 버그 수정')).toHaveCount(0);
    await expect(screen.getByText('차트 추가')).toBeVisible();

    await chip.tap();
    await expect(screen.getByText('로그인 버그 수정')).toBeVisible();
  });

  test('new ticket dialog creates a card in the chosen project', async ({ app, screen }) => {
    await openKanban(app, screen);
    await screen.getByRole('button', '새 티켓').tap();
    const dialog = screen.getByRole('dialog');
    await dialog.getByLabel('프로젝트').selectOption('beta-api');
    await dialog.getByLabel('제목').fill('e2e에서 만든 티켓');
    await dialog.getByRole('button', '만들기').tap();

    const card = screen.getByRole('button').filter({ hasText: 'e2e에서 만든 티켓' });
    await expect(card).toBeVisible();
    await expect(card).toContainText('beta-api');
  });
});

describe('session monitor', () => {
  async function event(baseUrl: string, body: Record<string, string>) {
    expect((await post(baseUrl, '/api/v1/unified/sessions/events', body)).status).toBe(200);
  }

  test('hook events appear as sessions and waiting is highlighted', async ({ app, screen }) => {
    const base = app.baseUrl!;
    await event(base, {
      hook_event_name: 'UserPromptSubmit', session_id: 'e2e-a',
      cwd: '/tmp/e2e-sessions/proj-one', prompt: '대시보드 차트 고쳐줘',
    });
    await openKanban(app, screen);
    const sessions = screen.getByRole('region', '내 세션');
    await expect(sessions.getByText('대시보드 차트 고쳐줘')).toBeVisible();
    await expect(sessions.getByText('작업 중').first()).toBeVisible();

    await event(base, {
      hook_event_name: 'Notification', session_id: 'e2e-a',
      cwd: '/tmp/e2e-sessions/proj-one', message: 'Claude needs your permission to use Bash',
    });
    await expect(sessions.getByText('Claude needs your permission to use Bash')).toBeVisible();
    await expect(sessions.getByText('나를 기다림').first()).toBeVisible();

    await event(base, { hook_event_name: 'SessionEnd', session_id: 'e2e-a', cwd: '/tmp/e2e-sessions/proj-one' });
    await expect(sessions.getByText('Claude needs your permission to use Bash')).toHaveCount(0);
  });
});

describe('session graph', () => {
  const cwd = '/tmp/e2e-graph/alpha';

  test('chart is the default view and links sessions to their folder', async ({ app, screen, browser }) => {
    const base = app.baseUrl!;
    for (const [id, prompt] of [['g-impl', '단위 변환 구현'], ['g-rev', '구현 리뷰']]) {
      expect((await post(base, '/api/v1/unified/sessions/events',
        { hook_event_name: 'UserPromptSubmit', session_id: id, cwd, prompt })).status).toBe(200);
    }
    await app.open('/');
    const chart = screen.getByRole('main', '세션 차트');
    await expect(screen.getByRole('tab', '차트')).toHaveAttribute('aria-selected', 'true');
    await expect(chart.getByText('단위 변환 구현')).toBeVisible();
    await expect(chart.getByText('구현 리뷰')).toBeVisible();
    await expect(browser.locator('.gnode.project').filter({ hasText: 'alpha' })).toHaveCount(1);

    // role badge persists through a reload
    const impl = browser.locator('.gcard[data-id="g-impl"]');
    await impl.getByLabel('역할').selectOption('implement');
    await app.open('/');
    await expect(browser.locator('.gcard[data-id="g-impl"]').getByLabel('역할')).toHaveValue('implement');

    // a thread name creates a middle node
    await browser.locator('.gcard[data-id="g-rev"]').getByRole('button', '+ 작업 줄기').tap();
    const input = chart.getByLabel('작업 줄기 이름');
    await input.fill('minor units');
    await input.press('Enter');
    await expect(browser.locator('.gnode.thread')).toHaveText('minor units');

    // arrows: created through the API, drawn, then removed
    expect((await post(base, '/api/v1/unified/sessions/edges', { from: 'g-impl', to: 'g-rev' })).status).toBe(201);
    expect((await post(base, '/api/v1/unified/sessions/edges', { from: 'g-rev', to: 'g-impl' })).status).toBe(409);
    await expect(browser.locator('.gedge-hit')).toHaveCount(1);
    await post(base, '/api/v1/unified/sessions/edges', { from: 'g-impl', to: 'g-rev' }, 'DELETE');
    await expect(browser.locator('.gedge-hit')).toHaveCount(0);

    // kanban is one click away and remembered
    await screen.getByRole('tab', '칸반').tap();
    await expect(chart).toBeHidden();
    await app.open('/');
    await expect(screen.getByRole('tab', '칸반')).toHaveAttribute('aria-selected', 'true');
  });
});

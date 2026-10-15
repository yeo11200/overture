import { describe, test } from '@e2e-dev/web';
import { expect } from 'e2e';

describe('unified board', () => {
  test('shows tickets from every project on one board', async ({ app, screen }) => {
    await app.open('/');
    const todo = screen.getByRole('region', 'Todo');
    await expect(todo.getByText('로그인 버그 수정')).toBeVisible();
    await expect(todo.getByText('차트 추가')).toBeVisible();
    await expect(todo.getByText('캐시 튜닝')).toBeVisible();
    await expect(screen.getByText('alpha-app').first()).toBeVisible();
  });

  test('project chip filters its cards out and back in', async ({ app, screen }) => {
    await app.open('/');
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
    await app.open('/');
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

// Unified board: every project's tickets on one screen, polled every 2s.
(() => {
  'use strict';

  const API = '/api/v1/unified';
  const POLL_MS = 2000;
  const REVIEW_LANE = 'human review';
  const STATUS_LABEL = {
    running: '실행 중',
    paused: '일시정지',
    error: '오류',
    conflict: '충돌',
    missing: '없음',
    unsupported: '미지원',
    starting: '시작 중',
  };

  const $ = (id) => document.getElementById(id);
  const els = {
    summary: $('summary'),
    search: $('search'),
    projects: $('projects'),
    notice: $('notice'),
    board: $('board'),
    drawer: $('drawer'),
    dialog: $('ticket-dialog'),
    form: $('ticket-form'),
    formError: $('ticket-error'),
    ticketProject: $('ticket-project'),
  };

  let data = { projects: [], columns: [], cards: [] };
  let discovery = { failures: {} };
  let lastRender = '';
  let openCard = null; // {project_id, identifier}
  const hidden = new Set(loadHidden());

  function loadHidden() {
    try { return JSON.parse(localStorage.getItem('unified.hidden') || '[]'); } catch { return []; }
  }
  function saveHidden() {
    try { localStorage.setItem('unified.hidden', JSON.stringify([...hidden])); } catch { /* private mode */ }
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
    ));
  }

  // Stable per-project hue so a project keeps its color across reloads.
  function color(id) {
    let hash = 0;
    for (const ch of id) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
    return `hsl(${hash % 360} 65% 52%)`;
  }

  async function api(path, options = {}) {
    const init = { ...options, headers: { 'Content-Type': 'application/json' } };
    const resp = await fetch(API + path, init);
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(body?.error?.message || `HTTP ${resp.status}`);
    return body;
  }

  function projectName(id) {
    return data.projects.find((p) => p.id === id)?.name ?? id;
  }

  function visibleCards() {
    const q = els.search.value.trim().toLowerCase();
    return data.cards.filter((c) => !hidden.has(c.project_id) && (
      !q || `${c.identifier} ${c.title} ${projectName(c.project_id)}`.toLowerCase().includes(q)
    ));
  }

  function liveBadge(live) {
    if (!live) return '';
    if (live.status === 'retrying') {
      return `<span class="badge retrying">↻ 재시도 대기${live.attempt ? ` #${esc(live.attempt)}` : ''}</span>`;
    }
    const turn = live.turn_count ? `턴 ${esc(live.turn_count)}` : '실행 중';
    const event = live.last_event ? ` · ${esc(live.last_event)}` : '';
    return `<span class="badge running">${turn}${event}</span>`;
  }

  function renderProjects() {
    const counts = {};
    for (const c of data.cards) counts[c.project_id] = (counts[c.project_id] || 0) + 1;
    els.projects.innerHTML = data.projects.map((p) => {
      const on = !hidden.has(p.id);
      const canToggle = p.status === 'running' || p.status === 'paused';
      const title = p.error ? ` title="${esc(p.error)}"` : '';
      return `
        <span class="chip${on ? '' : ' off'}" style="--c:${color(p.id)}"${title}>
          <button type="button" class="chip-main" data-filter="${esc(p.id)}" aria-pressed="${on}">
            <span class="dot"></span>${esc(p.name)}
            <span class="chip-count">${counts[p.id] || 0}</span>
          </button>
          ${p.status === 'running' ? '' : `<span class="chip-state ${esc(p.status)}">${STATUS_LABEL[p.status] || esc(p.status)}</span>`}
          <button type="button" class="chip-toggle" data-pause="${esc(p.id)}" data-paused="${p.paused}"
            aria-label="${p.paused ? '재개' : '일시정지'}" title="${p.paused ? '재개' : '새 작업 일시정지'}"
            ${canToggle ? '' : 'disabled'}>${p.paused ? '▶' : '❚❚'}</button>
        </span>`;
    }).join('');
  }

  function renderNotice() {
    const rows = Object.entries(discovery.failures || {}).map(([path, info]) => `
      <div class="notice-row">자동 등록 실패: <code>${esc(path)}</code> — ${esc(String(info.error).slice(0, 160))}
        <button type="button" class="btn" data-retry="${esc(path)}">다시 시도</button></div>`);
    els.notice.innerHTML = rows.join('');
    els.notice.hidden = rows.length === 0;
  }

  function renderBoard() {
    const cards = visibleCards();
    els.board.innerHTML = data.columns.map((col) => {
      const inCol = cards.filter((c) => c.state === col.name);
      const review = col.name.toLowerCase() === REVIEW_LANE;
      const body = inCol.length
        ? inCol.map((c) => `
          <button type="button" class="card" style="--c:${color(c.project_id)}"
            data-project="${esc(c.project_id)}" data-id="${esc(c.identifier)}">
            <div class="card-top">
              <span class="card-project">${esc(projectName(c.project_id))}</span>
              <span class="card-id">${esc(c.identifier)}</span>
            </div>
            <p class="card-title">${esc(c.title)}</p>
            ${liveBadge(c.live)}
          </button>`).join('')
        : '<div class="empty">비어 있음</div>';
      return `
        <section class="column${review ? ' review' : ''}" aria-label="${esc(col.name)}">
          <div class="column-head"><span>${esc(col.name)}</span><span class="count">${inCol.length}</span></div>
          <div class="cards">${body}</div>
        </section>`;
    }).join('');
  }

  function renderSummary() {
    const running = data.cards.filter((c) => c.live?.status === 'running').length;
    const review = data.cards.filter((c) => c.state.toLowerCase() === REVIEW_LANE).length;
    const hosted = data.projects.filter((p) => p.status === 'running' || p.status === 'paused').length;
    els.summary.textContent = `프로젝트 ${hosted}/${data.projects.length} · 실행 중 ${running} · 확인 대기 ${review}`;
    document.title = review ? `(${review}) 통합 보드` : '통합 보드';
  }

  function render(force = false) {
    const key = JSON.stringify([data, discovery, els.search.value, [...hidden]]);
    if (!force && key === lastRender) return;
    lastRender = key;
    renderSummary();
    renderProjects();
    renderNotice();
    renderBoard();
  }

  async function refresh() {
    try {
      [data, discovery] = await Promise.all([api('/board'), api('/discovery')]);
      render();
      if (openCard) refreshDrawer();
    } catch (err) {
      els.summary.textContent = `연결 끊김: ${err.message}`;
    }
  }

  async function refreshDrawer() {
    const { project_id: pid, identifier } = openCard;
    try {
      const d = await api(`/projects/${encodeURIComponent(pid)}/issues/${encodeURIComponent(identifier)}`);
      if (!openCard || openCard.identifier !== identifier || openCard.project_id !== pid) return;
      $('drawer-project').innerHTML = `<span class="dot" style="--c:${color(pid)}"></span>${esc(projectName(pid))} · ${esc(d.identifier)}`;
      $('drawer-title').textContent = d.title || d.identifier;
      const meta = [
        ['상태', d.state],
        ['우선순위', d.priority ?? '—'],
        ['에이전트', d.agent_kind || d.last_agent_kind || '기본'],
        ['실행', d.live ? `${d.live.status} · 턴 ${d.live.turn_count ?? 0}` : '—'],
        ['마지막 이벤트', d.live?.last_event || '—'],
        ['수정', d.updated_at ? new Date(d.updated_at).toLocaleString('ko-KR') : '—'],
      ];
      $('drawer-meta').innerHTML = meta.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
      $('drawer-body').textContent = d.description || '(설명 없음)';
      els.drawer.hidden = false;
    } catch (err) {
      $('drawer-body').textContent = `불러오기 실패: ${err.message}`;
    }
  }

  function openNewTicket() {
    const hosted = data.projects.filter((p) => p.status === 'running' || p.status === 'paused');
    els.ticketProject.innerHTML = hosted
      .map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
    els.form.reset();
    els.formError.textContent = '';
    els.dialog.showModal();
  }

  // -- events -------------------------------------------------------------

  els.projects.addEventListener('click', async (event) => {
    const filter = event.target.closest('[data-filter]');
    if (filter) {
      const id = filter.dataset.filter;
      if (hidden.has(id)) hidden.delete(id); else hidden.add(id);
      saveHidden();
      render(true);
      return;
    }
    const toggle = event.target.closest('[data-pause]');
    if (toggle && !toggle.disabled) {
      const action = toggle.dataset.paused === 'true' ? 'resume' : 'pause';
      toggle.disabled = true;
      try {
        await api(`/projects/${encodeURIComponent(toggle.dataset.pause)}/${action}`, { method: 'POST', body: '{}' });
      } catch (err) {
        alert(`실패: ${err.message}`);
      }
      refresh();
    }
  });

  els.notice.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-retry]');
    if (!btn) return;
    btn.disabled = true;
    try {
      await api('/discovery/retry', { method: 'POST', body: JSON.stringify({ path: btn.dataset.retry }) });
    } catch (err) {
      alert(`실패: ${err.message}`);
    }
    refresh();
  });

  els.board.addEventListener('click', (event) => {
    const card = event.target.closest('.card');
    if (!card) return;
    openCard = { project_id: card.dataset.project, identifier: card.dataset.id };
    refreshDrawer();
  });

  $('drawer-close').addEventListener('click', () => { openCard = null; els.drawer.hidden = true; });
  els.search.addEventListener('input', () => render(true));
  $('new-ticket').addEventListener('click', openNewTicket);
  $('ticket-cancel').addEventListener('click', () => els.dialog.close());

  els.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(els.form);
    const priority = form.get('priority');
    try {
      await api(`/projects/${encodeURIComponent(form.get('project'))}/issues`, {
        method: 'POST',
        body: JSON.stringify({
          title: form.get('title'),
          description: form.get('description'),
          priority: priority ? Number(priority) : null,
        }),
      });
      els.dialog.close();
      refresh();
    } catch (err) {
      els.formError.textContent = err.message;
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !els.drawer.hidden) {
      openCard = null;
      els.drawer.hidden = true;
    }
    const tag = document.activeElement?.tagName;
    if (event.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
      event.preventDefault();
      els.search.focus();
    }
  });

  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();

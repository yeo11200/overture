// Session graph: project → thread → agent card, with dependency arrows.
// HTML cards are absolutely positioned; one SVG underneath draws the links.
(() => {
  'use strict';

  const X = { project: 24, thread: 290, card: 560 };
  const W = { project: 200, thread: 200, card: 300 };
  const CARD_H = 92;
  const GAP = 14;
  const GROUP_GAP = 36;
  const TOP = 20;
  const NODE_H = 44;
  const ROLES = ['main', 'plan', 'implement', 'review', 'experiment'];
  const STATE_LABEL = {
    working: '작업 중', waiting: '나를 기다림', done: '완료', idle: '대기', unknown: '상태 모름',
  };

  let busy = false; // a drag, an open role menu or a thread edit owns the screen
  let ctx = null; // { root, api, refresh }

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  function ago(epochSeconds) {
    if (!epochSeconds) return '';
    const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
    if (s < 60) return `${s}초`;
    if (s < 3600) return `${Math.floor(s / 60)}분`;
    if (s < 86400) return `${Math.floor(s / 3600)}시간`;
    return `${Math.floor(s / 86400)}일`;
  }

  function cardsOf(group) {
    const cards = group.sessions;
    // Threaded cards first, in first-seen thread order, so each thread node
    // sits next to a contiguous block of its cards.
    const order = [];
    for (const c of cards) if (c.thread && !order.includes(c.thread)) order.push(c.thread);
    return [
      ...order.flatMap((t) => cards.filter((c) => c.thread === t)),
      ...cards.filter((c) => !c.thread),
    ];
  }

  function layout(groups) {
    let y = TOP;
    const placed = [];
    for (const group of groups) {
      const cards = cardsOf(group).map((card) => {
        const pos = { ...card, x: X.card, y };
        y += CARD_H + GAP;
        return pos;
      });
      const mid = (list) => (list[0].y + list[list.length - 1].y + CARD_H) / 2;
      const threads = [...new Set(cards.filter((c) => c.thread).map((c) => c.thread))].map((name) => ({
        name, y: mid(cards.filter((c) => c.thread === name)) - NODE_H / 2,
      }));
      placed.push({ group, cards, threads, y: mid(cards) - NODE_H / 2 });
      y += GROUP_GAP - GAP;
    }
    return { placed, height: Math.max(y, 200) };
  }

  const link = (x1, y1, x2, y2) => {
    const dx = Math.max(40, (x2 - x1) / 2);
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  };
  const arrow = (x1, y1, x2, y2) => {
    const bow = 70 + Math.min(120, Math.abs(y2 - y1) / 4);
    return `M${x1},${y1} C${x1 + bow},${y1} ${x2 + bow},${y2} ${x2 + 10},${y2}`;
  };

  function cardHtml(c, color) {
    const title = c.title || `${c.tool === 'codex' ? 'Codex' : 'Claude'} · ${c.folder}`;
    const sub = [c.tool, c.folder, c.branch].filter(Boolean).join(' · ');
    const text = c.state === 'waiting' && c.message ? c.message : c.prompt || STATE_LABEL[c.state];
    const options = ['', ...ROLES].map((r) => (
      `<option value="${r}"${r === (c.role || '') ? ' selected' : ''}>${r || '역할'}</option>`
    )).join('');
    return `<div class="gcard ${esc(c.state)}" data-id="${esc(c.id)}" style="left:${c.x}px;top:${c.y}px;--c:${color}"
        title="${esc(c.cwd)}">
      <div class="gcard-top">
        <span class="sdot ${esc(c.state)}" title="${STATE_LABEL[c.state] || ''}"></span>
        <span class="gtitle">${esc(title)}</span>
        <select class="grole${c.role ? ' set' : ''}" data-role-for="${esc(c.id)}" aria-label="역할">${options}</select>
      </div>
      <div class="gsub">${esc(sub)}</div>
      <div class="gline"><span class="gtext">${esc(text)}</span><span class="gago">${ago(c.updated_at)}</span></div>
      <button type="button" class="gthread" data-thread-for="${esc(c.id)}">${c.thread ? `# ${esc(c.thread)}` : '+ 작업 줄기'}</button>
      <span class="gport" data-port="${esc(c.id)}" title="다른 카드로 끌어서 의존 관계 연결"></span>
    </div>`;
  }

  function renderList(root, groups, color) {
    root.innerHTML = groups.map((g) => `
      <section class="glist" style="--c:${color(g.project_id || g.key)}">
        <h3><span class="dot"></span>${esc(g.name)}</h3>
        ${cardsOf(g).map((c) => cardHtml({ ...c, x: 0, y: 0 }, color(g.project_id || g.key))).join('')}
      </section>`).join('');
  }

  function render(root, data, { color, api, refresh }) {
    ctx = { root, api, refresh };
    if (busy) return;
    const groups = data.groups || [];
    if (!groups.length) {
      root.innerHTML = '<div class="gempty">실행 중인 Claude Code·Codex 세션이 없어요.<br>터미널에서 Claude Code를 띄우면 여기에 나타납니다.</div>';
      return;
    }
    root.classList.toggle('narrow', root.clientWidth < 720);
    if (root.clientWidth < 720) {
      renderList(root, groups, color);
      return;
    }
    const { placed, height } = layout(groups);
    const pos = new Map(placed.flatMap((p) => p.cards.map((c) => [c.id, c])));
    const lines = [];
    const nodes = [];
    for (const p of placed) {
      const c = color(p.group.project_id || p.group.key);
      const py = p.y + NODE_H / 2;
      nodes.push(`<div class="gnode project" style="left:${X.project}px;top:${p.y}px;--c:${c}">
        <span class="dot"></span><span>${esc(p.group.name)}</span>
        <span class="gcount">${p.cards.length}</span></div>`);
      for (const t of p.threads) {
        nodes.push(`<div class="gnode thread" style="left:${X.thread}px;top:${t.y}px;--c:${c}">${esc(t.name)}</div>`);
        lines.push(link(X.project + W.project, py, X.thread, t.y + NODE_H / 2));
      }
      for (const card of p.cards) {
        const cy = card.y + CARD_H / 2;
        const thread = p.threads.find((t) => t.name === card.thread);
        lines.push(thread
          ? link(X.thread + W.thread, thread.y + NODE_H / 2, X.card, cy)
          : link(X.project + W.project, py, X.card, cy));
      }
    }
    const edges = (data.edges || []).filter(([a, b]) => pos.has(a) && pos.has(b)).map(([a, b]) => {
      const s = pos.get(a);
      const t = pos.get(b);
      const d = arrow(X.card + W.card, s.y + CARD_H / 2, X.card + W.card, t.y + CARD_H / 2);
      return `<path class="gedge" d="${d}" marker-end="url(#garrow)"/>
        <path class="gedge-hit" d="${d}" data-from="${esc(a)}" data-to="${esc(b)}"><title>클릭해서 연결 끊기</title></path>`;
    });
    const width = X.card + W.card + 260;
    root.innerHTML = `
      <div class="gcanvas" style="width:${width}px;height:${height}px">
        <svg class="glinks" width="${width}" height="${height}">
          <defs><marker id="garrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z"/></marker></defs>
          ${lines.map((d) => `<path class="glink" d="${d}"/>`).join('')}
          ${edges.join('')}
          <path class="gdrag" d="" marker-end="url(#garrow)"/>
        </svg>
        ${nodes.join('')}
        ${placed.flatMap((p) => p.cards.map((c) => cardHtml(c, color(p.group.project_id || p.group.key)))).join('')}
      </div>`;
  }

  // -- interactions (delegated once on the root) -------------------------------

  function attach(root) {
    root.addEventListener('change', async (e) => {
      const select = e.target.closest('[data-role-for]');
      if (!select) return;
      busy = false;
      try {
        await ctx.api(`/sessions/${encodeURIComponent(select.dataset.roleFor)}`, {
          method: 'PATCH', body: JSON.stringify({ role: select.value }),
        });
      } catch (err) { alert(`역할 저장 실패: ${err.message}`); }
      ctx.refresh(true);
    });
    root.addEventListener('focusin', (e) => { if (e.target.matches('select, input')) busy = true; });
    root.addEventListener('focusout', (e) => { if (e.target.matches('select')) busy = false; });

    root.addEventListener('click', async (e) => {
      const hit = e.target.closest('.gedge-hit');
      if (hit) {
        try {
          await ctx.api('/sessions/edges', {
            method: 'DELETE', body: JSON.stringify({ from: hit.dataset.from, to: hit.dataset.to }),
          });
        } catch (err) { alert(`연결 삭제 실패: ${err.message}`); }
        ctx.refresh(true);
        return;
      }
      const btn = e.target.closest('[data-thread-for]');
      if (!btn) return;
      const id = btn.dataset.threadFor;
      const current = btn.textContent.startsWith('# ') ? btn.textContent.slice(2) : '';
      const input = document.createElement('input');
      input.className = 'gthread-input';
      input.value = current;
      input.maxLength = 40;
      input.placeholder = '작업 줄기 이름 (비우면 해제)';
      input.setAttribute('aria-label', '작업 줄기 이름');
      btn.replaceWith(input);
      busy = true;
      input.focus();
      let done = false;
      const save = async (commit) => {
        if (done) return;
        done = true;
        busy = false;
        if (commit && input.value.trim() !== current) {
          try {
            await ctx.api(`/sessions/${encodeURIComponent(id)}`, {
              method: 'PATCH', body: JSON.stringify({ thread: input.value }),
            });
          } catch (err) { alert(`작업 줄기 저장 실패: ${err.message}`); }
        }
        ctx.refresh(true);
      };
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') save(true);
        if (ev.key === 'Escape') save(false);
      });
      input.addEventListener('blur', () => save(true));
    });

    root.addEventListener('pointerdown', (e) => {
      const port = e.target.closest('[data-port]');
      if (!port) return;
      e.preventDefault();
      busy = true;
      const canvas = root.querySelector('.gcanvas');
      const drag = root.querySelector('.gdrag');
      const box = canvas.getBoundingClientRect();
      const card = port.closest('.gcard');
      const sx = X.card + W.card;
      const sy = card.offsetTop + CARD_H / 2;
      const move = (ev) => {
        const x = ev.clientX - box.left;
        const y = ev.clientY - box.top;
        drag.setAttribute('d', `M${sx},${sy} C${sx + 80},${sy} ${x + 80},${y} ${x},${y}`);
      };
      const up = async (ev) => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        drag.setAttribute('d', '');
        busy = false;
        const target = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.gcard[data-id]');
        if (target && target.dataset.id !== port.dataset.port) {
          try {
            await ctx.api('/sessions/edges', {
              method: 'POST', body: JSON.stringify({ from: port.dataset.port, to: target.dataset.id }),
            });
          } catch (err) { alert(`연결 실패: ${err.message}`); }
        }
        ctx.refresh(true);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
  }

  window.UnifiedGraph = { render, attach, isBusy: () => busy };
})();

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

  // simple-icons (CC0): `claude` 16.35.0 and `openai` 13.21.0 — Codex has no mark of its own.
  // The marks remain trademarks of Anthropic and OpenAI.
  const ICON_PATHS = {
    claude: 'm4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z',
    codex: 'M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z',
  };
  const ICON_NAMES = { claude: 'Claude', codex: 'Codex' };
  const icon = (tool) => (ICON_PATHS[tool]
    ? `<svg class="gicon ${tool}" viewBox="0 0 24 24" role="img" aria-label="${ICON_NAMES[tool]}"><path d="${ICON_PATHS[tool]}"/></svg>`
    : '');

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
    const sub = [c.folder, c.branch].filter(Boolean).join(' · ');
    const text = c.state === 'waiting' && c.message ? c.message : c.prompt || STATE_LABEL[c.state];
    const options = ['', ...ROLES].map((r) => (
      `<option value="${r}"${r === (c.role || '') ? ' selected' : ''}>${r || '역할'}</option>`
    )).join('');
    return `<div class="gcard ${esc(c.state)}" data-id="${esc(c.id)}" style="left:${c.x}px;top:${c.y}px;--c:${color}"
        title="${esc(c.cwd)}">
      <div class="gcard-top">
        <span class="sdot ${esc(c.state)}" title="${STATE_LABEL[c.state] || ''}"></span>
        ${icon(c.tool)}
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

  window.UnifiedGraph = { render, attach, icon, isBusy: () => busy };
})();

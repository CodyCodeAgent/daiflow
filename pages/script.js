/* ══════════════════════════════════════
   DaiFlow Site — script.js
══════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initHamburger();
  initScrollAnimations();
  initTerminal();
  initCopyButtons();
  initDocsSidebar();
  initCounters();
});

/* ── Navbar scroll effect ── */
function initNav() {
  const nav = document.querySelector('.nav');
  if (!nav) return;
  const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > 30);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

/* ── Mobile hamburger menu ──
   Toggles .nav-mobile-panel.open and animates the ☰ button. */
function initHamburger() {
  const btn   = document.getElementById('hamburger');
  const panel = document.getElementById('nav-mobile-panel');
  if (!btn || !panel) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = panel.classList.toggle('open');
    btn.classList.toggle('open', isOpen);
    btn.setAttribute('aria-expanded', String(isOpen));
  });

  // Close when clicking outside nav area
  document.addEventListener('click', (e) => {
    if (!btn.contains(e.target) && !panel.contains(e.target)) {
      panel.classList.remove('open');
      btn.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    }
  });

  // Close when a panel link is tapped
  panel.querySelectorAll('a').forEach(a => {
    a.addEventListener('click', () => {
      panel.classList.remove('open');
      btn.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    });
  });
}

/* ── Intersection Observer scroll animations ── */
function initScrollAnimations() {
  // Respect prefers-reduced-motion
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.querySelectorAll('.anim').forEach(el => el.classList.add('visible'));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('visible'); }),
    { threshold: 0.08, rootMargin: '0px 0px -40px 0px' }
  );
  document.querySelectorAll('.anim').forEach(el => observer.observe(el));
}

/* ── Terminal typing animation ──
   FIX #1: white-space:pre on terminal-body handles space preservation.
   FIX #3: Prompt $ rendered with correct teal color via separate span. */
function initTerminal() {
  const body = document.getElementById('term-body');
  if (!body) return;

  // Respect reduced motion — skip animation, show static content
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    body.innerHTML = renderStaticTerminal();
    return;
  }

  const lines = [
    /* prompt line rendered specially: $ in teal, command in white */
    { html: '<span class="t-prompt">$ </span><span class="t-cmd">daiflow start</span>', delay: 350 },
    { text: '', delay: 180 },
    { text: '  ██████╗  █████╗ ██╗███████╗██╗     ██████╗ ██╗    ██╗', cls: 't-info', instant: true, delay: 0 },
    { text: '  ██╔══██╗██╔══██╗██║██╔════╝██║    ██╔═══██╗██║    ██║', cls: 't-info', instant: true, delay: 0 },
    { text: '  ██║  ██║███████║██║█████╗  ██║    ██║   ██║██║ █╗ ██║', cls: 't-info', instant: true, delay: 0 },
    { text: '  ██║  ██║██╔══██║██║██╔══╝  ██║    ██║   ██║██║███╗██║', cls: 't-info', instant: true, delay: 0 },
    { text: '  ██████╔╝██║  ██║██║██║     ███████╗╚██████╔╝╚███╔███╔╝', cls: 't-info', instant: true, delay: 40 },
    { text: '  ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝', cls: 't-info', instant: true, delay: 180 },
    { text: '', delay: 80 },
    { text: '✓ 数据库初始化完成', cls: 't-ok', delay: 220 },
    { text: '✓ AI 引擎已就绪 (Cody SDK)', cls: 't-ok', delay: 180 },
    { text: '✓ 服务已启动 → http://localhost:8000', cls: 't-ok', delay: 220 },
    { text: '', delay: 80 },
    { text: '📋 当前任务: 实现用户认证模块', cls: 't-dim', delay: 300 },
    { text: '', delay: 80 },
    { text: '阶段 2/5 ─ 技术方案生成中...', cls: 't-stage', delay: 180 },
    { text: '  ✦ JWT + Refresh Token 双 Token 方案', cls: 't-dim', delay: 130 },
    { text: '  ✦ bcrypt 密码加密', cls: 't-dim', delay: 110 },
    { text: '  ✦ Redis 会话存储', cls: 't-dim', delay: 110 },
    { text: '✓ plan.md 已生成 (1.2 KB)', cls: 't-ok', delay: 260 },
    { text: '', delay: 60 },
    { text: '阶段 3/5 ─ 任务拆解...', cls: 't-stage', delay: 180 },
    { text: '✓ 已生成 5 个 Todo', cls: 't-ok', delay: 220 },
    { text: '', delay: 60 },
    { text: '[1] ✓ 创建用户数据模型', cls: 't-ok', delay: 90 },
    { text: '[2] ✓ 实现注册接口', cls: 't-ok', delay: 90 },
    { text: '[3] → 实现登录 & Token 刷新接口', cls: 't-info', delay: 90 },
  ];

  let charTimerId = null;
  let cancelled   = false;

  function appendHTML(html) {
    const span = document.createElement('span');
    span.style.display = 'block';
    span.innerHTML = html;
    body.appendChild(span);
    body.scrollTop = body.scrollHeight;
    return Promise.resolve();
  }

  function appendLine(text, cls = '', instant = false) {
    const span = document.createElement('span');
    span.style.display = 'block';
    if (cls) span.className = cls;
    body.appendChild(span);

    if (!text) {
      span.textContent = '\u00a0'; // non-breaking space keeps line height
      return Promise.resolve();
    }

    if (instant) {
      span.textContent = text;
      body.scrollTop = body.scrollHeight;
      return Promise.resolve();
    }

    return new Promise(resolve => {
      let i = 0;
      const speed = 20;
      const cursor = document.createElement('span');
      cursor.className = 't-cursor';
      span.appendChild(cursor);

      const tick = () => {
        if (cancelled) { resolve(); return; }
        if (i < text.length) {
          span.textContent = text.slice(0, ++i);
          span.appendChild(cursor);
          body.scrollTop = body.scrollHeight;
          charTimerId = setTimeout(tick, speed);
        } else {
          cursor.remove();
          resolve();
        }
      };
      tick();
    });
  }

  async function runLines() {
    for (const line of lines) {
      if (cancelled) break;

      if (line.html) {
        await appendHTML(line.html);
      } else {
        await appendLine(line.text, line.cls || '', line.instant || false);
      }
      await sleep(line.delay ?? 100);
    }

    if (!cancelled) {
      const cur = document.createElement('span');
      cur.className = 't-cursor';
      body.appendChild(cur);
    }
  }

  // Start only when terminal scrolls into view
  const observer = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting) {
      observer.disconnect();
      runLines();
    }
  }, { threshold: 0.3 });
  observer.observe(body);

  // Cancel animation if user scrolls away (saves CPU)
  const cancelObserver = new IntersectionObserver(([entry]) => {
    if (!entry.isIntersecting) { cancelled = true; clearTimeout(charTimerId); }
  }, { threshold: 0 });
  cancelObserver.observe(body);
}

function renderStaticTerminal() {
  return `<span class="t-prompt">$ </span><span class="t-cmd">daiflow start</span>
<span class="t-ok">✓ 数据库初始化完成</span>
<span class="t-ok">✓ AI 引擎已就绪 (Cody SDK)</span>
<span class="t-ok">✓ 服务已启动 → http://localhost:8000</span>
<span class="t-dim">📋 当前任务: 实现用户认证模块</span>
<span class="t-stage">阶段 3/5 ─ 任务拆解...</span>
<span class="t-ok">✓ 已生成 5 个 Todo</span>
<span class="t-ok">[1] ✓ 创建用户数据模型</span>
<span class="t-ok">[2] ✓ 实现注册接口</span>
<span class="t-info">[3] → 实现登录 & Token 刷新接口</span>`;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* ── Copy buttons ──
   FIX #7: Better regex — only strips leading "$ " shell prompts per line.
   FIX #8: Clipboard API fallback for HTTP / old browsers. */
function initCopyButtons() {
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const block = btn.closest('.code-window, .doc-code');
      if (!block) return;
      const pre = block.querySelector('pre, .code-win-body');
      if (!pre) return;

      // Strip only leading `$ ` shell prompt from each line
      const raw  = pre.innerText;
      const text = raw.replace(/^[ \t]*\$[ \t]/gm, '').trim();

      const orig = btn.textContent;
      const done = () => {
        btn.textContent  = '✓ 已复制';
        btn.style.color  = 'var(--green)';
        setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 2000);
      };
      const fail = () => {
        btn.textContent = '复制失败';
        btn.style.color = 'var(--red)';
        setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 2000);
      };

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(fail);
      } else {
        // Fallback: create a temporary textarea
        try {
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          ta.remove();
          done();
        } catch { fail(); }
      }
    });
  });
}

/* ── Docs sidebar active link on scroll ──
   Keeps at least one link active at all times by tracking the
   "most recently entered" section rather than removing on exit. */
function initDocsSidebar() {
  const links = document.querySelectorAll('.ds-link[href^="#"]');
  if (!links.length) return;

  let current = links[0]; // default to first link

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          const id = e.target.getAttribute('id');
          const match = [...links].find(l => l.getAttribute('href') === `#${id}`);
          if (match) {
            current.classList.remove('active');
            match.classList.add('active');
            current = match;
          }
        }
      });
    },
    { rootMargin: '-15% 0px -65% 0px' }
  );

  links.forEach(link => {
    const target = document.querySelector(link.getAttribute('href'));
    if (target) observer.observe(target);
  });
}

/* ── Animated counters ── */
function initCounters() {
  const counters = document.querySelectorAll('[data-count]');
  if (!counters.length) return;

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    counters.forEach(el => {
      el.textContent = el.dataset.count + (el.dataset.suffix || '');
    });
    return;
  }

  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (!e.isIntersecting) return;
      observer.unobserve(e.target);
      const el       = e.target;
      const target   = parseInt(el.dataset.count, 10);
      const suffix   = el.dataset.suffix || '';
      const duration = 900; // shorter — small numbers (3, 5) feel better at 900ms
      const start    = performance.now();

      const tick = (now) => {
        const p   = Math.min((now - start) / duration, 1);
        const val = Math.round(easeOut(p) * target);
        el.textContent = val + suffix;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }, { threshold: 0.5 });

  counters.forEach(el => observer.observe(el));
}

function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

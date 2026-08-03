(function () {
  'use strict';
  // ============================================================
  //  CCTS — Lấy TOKEN (body) + COOKIE để dán vào app (bước 3)
  //  Tab console.cnpowercore.com đã login -> F12 -> Console -> dán -> Enter.
  //  Panel hiện 2 ô: Token và Cookie, mỗi ô 1 nút Copy.
  //  - Token: tự tìm trong storage, hoặc bắt từ request (bấm Search 1 lần nếu chưa có).
  //  - Cookie: đọc document.cookie. Nếu cookie phiên là HttpOnly -> JS không đọc được,
  //    lấy tay ở DevTools > Network > findCCTSTicket > Request Headers > cookie.
  // ============================================================

  const PANEL_ID = 'ccts-cred-panel', STYLE_ID = 'ccts-cred-style';
  document.getElementById(PANEL_ID)?.remove();
  document.getElementById(STYLE_ID)?.remove();

  const looksLikeToken = (s) => typeof s === 'string' && s.length >= 100 && /^[A-Za-z0-9+/=]+$/.test(s);
  function deepFindToken(o, d) {
    d = d || 0;
    if (!o || typeof o !== 'object' || d > 6) return null;
    for (const k of Object.keys(o)) {
      const v = o[k];
      if (/token/i.test(k) && looksLikeToken(v)) return v;
      if (v && typeof v === 'object') { const r = deepFindToken(v, d + 1); if (r) return r; }
    }
    return null;
  }
  function scanStorage() {
    for (const st of [localStorage, sessionStorage]) {
      for (let i = 0; i < st.length; i++) {
        const k = st.key(i), raw = st.getItem(k) || '';
        if (/token/i.test(k) && looksLikeToken(raw)) return raw;
        try { const t = deepFindToken(JSON.parse(raw)); if (t) return t; } catch (e) {}
      }
    }
    return null;
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); return true; }
    catch (e) {
      try { const a = document.createElement('textarea'); a.value = t; a.style.cssText = 'position:fixed;top:-1000px;opacity:0'; document.body.appendChild(a); a.focus(); a.select(); const ok = document.execCommand('copy'); a.remove(); return ok; }
      catch (_) { return false; }
    }
  }

  let TOKEN = scanStorage();
  const COOKIE = document.cookie || '';
  if (TOKEN) window.__cctsToken = TOKEN;
  window.__cctsCookie = COOKIE;

  // hook để bắt token nếu chưa có sẵn trong storage
  if (!window.__cctsCredHook) {
    window.__cctsCredHook = true;
    const grab = (url, body) => {
      try {
        if (!/\/ccts\//i.test(url || '') || typeof body !== 'string') return;
        const t = deepFindToken(JSON.parse(body));
        if (t) { TOKEN = t; window.__cctsToken = t; if (window.__cctsCredRefresh) window.__cctsCredRefresh(); }
      } catch (e) {}
    };
    const _f = window.fetch;
    window.fetch = function (input, init) {
      try { grab(typeof input === 'string' ? input : (input && input.url) || '', init && init.body); } catch (e) {}
      return _f.apply(this, arguments);
    };
    const Xo = XMLHttpRequest.prototype.open, Xs = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) { this.__u = u; return Xo.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function (b) { grab(this.__u, b); return Xs.apply(this, arguments); };
  }

  // ----- UI -----
  const style = document.createElement('style'); style.id = STYLE_ID;
  style.textContent = `
  #${PANEL_ID}{position:fixed;top:16px;right:16px;z-index:2147483000;width:340px;background:#fff;border:1px solid #dcdfe6;border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,.18);font:13px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#303133}
  #${PANEL_ID} .h{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #eee}
  #${PANEL_ID} .h b{flex:1}
  #${PANEL_ID} .h button{background:transparent;border:0;font-size:16px;cursor:pointer;color:#909399;line-height:1}
  #${PANEL_ID} .bd{padding:12px}
  #${PANEL_ID} .lbl{font-size:12px;font-weight:600;color:#606266;margin:2px 0 4px;display:flex;align-items:center;gap:6px}
  #${PANEL_ID} .lbl .dot{margin-left:auto;font-weight:400}
  #${PANEL_ID} textarea{width:100%;height:52px;box-sizing:border-box;font-family:monospace;font-size:11px;padding:6px;border:1px solid #dcdfe6;border-radius:6px;resize:vertical;background:#fafafa}
  #${PANEL_ID} .cp{width:100%;border:0;border-radius:6px;padding:7px 10px;margin:6px 0 12px;cursor:pointer;font-size:13px;font-weight:600;background:#409eff;color:#fff}
  #${PANEL_ID} .cp:disabled{background:#c8d6e5;cursor:default}
  #${PANEL_ID} .note{font-size:11px;color:#909399}
  #${PANEL_ID} .st{font-size:12px;color:#16a34a;min-height:16px}
  `;
  document.head.appendChild(style);

  const panel = document.createElement('div'); panel.id = PANEL_ID;
  panel.innerHTML = `
    <div class="h"><b>CCTS — Token & Cookie</b><button data-x="close" title="Đóng">×</button></div>
    <div class="bd">
      <div class="lbl">Token (body) <span class="dot" data-x="tstate"></span></div>
      <textarea data-x="tok" readonly placeholder="Đang tìm token..."></textarea>
      <button class="cp" data-x="ctok">📋 Copy Token</button>
      <div class="lbl">Cookie <span class="dot" data-x="cstate"></span></div>
      <textarea data-x="ck" readonly></textarea>
      <button class="cp" data-x="cck">📋 Copy Cookie</button>
      <div class="st" data-x="st"></div>
    </div>`;
  document.body.appendChild(panel);
  const $ = (s) => panel.querySelector(s);
  $('[data-x="close"]').onclick = () => panel.remove();
  const tokBox = $('[data-x="tok"]'), ckBox = $('[data-x="ck"]'),
        tstate = $('[data-x="tstate"]'), cstate = $('[data-x="cstate"]'),
        btnTok = $('[data-x="ctok"]'), stt = $('[data-x="st"]');

  ckBox.value = COOKIE;
  if (COOKIE.trim()) {
    cstate.innerHTML = '<span style="color:#16a34a">● đọc được</span>';
  } else {
    cstate.innerHTML = '<span style="color:#d9820a">● trống (HttpOnly?)</span>';
    ckBox.placeholder = 'document.cookie trống — cookie phiên có thể HttpOnly. Lấy ở DevTools > findCCTSTicket > Request Headers > cookie.';
  }

  window.__cctsCredRefresh = () => {
    if (TOKEN) {
      tokBox.value = TOKEN;
      tstate.innerHTML = '<span style="color:#16a34a">● có</span>';
      btnTok.disabled = false;
    } else {
      tstate.innerHTML = '<span style="color:#d9820a">● chưa có — bấm Search 1 lần</span>';
      btnTok.disabled = true;
    }
  };
  window.__cctsCredRefresh();

  btnTok.onclick = async () => {
    if (!TOKEN) return;
    stt.textContent = (await copyText(TOKEN)) ? '✓ Đã copy Token — dán vào ô "CCTS token" trong app.' : '✗ Copy lỗi (lấy ở window.__cctsToken).';
  };
  $('[data-x="cck"]').onclick = async () => {
    const v = ckBox.value.trim();
    if (!v) { stt.textContent = 'Cookie trống — lấy tay ở DevTools (Request Headers > cookie).'; return; }
    stt.textContent = (await copyText(v)) ? '✓ Đã copy Cookie — dán vào ô "CCTS cookie" trong app.' : '✗ Copy lỗi.';
  };

  console.log('[CCTS cred] token -> window.__cctsToken | cookie -> window.__cctsCookie');
})();

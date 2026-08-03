(function () {
  'use strict';
  // ============================================================
  //  CCTS — Lấy trạng thái theo list RC, CHẠY TRONG TAB (không dính 511)
  //  Tab console.cnpowercore.com đã login -> F12 -> Console -> dán file -> Enter.
  //  Panel hiện góc phải: dán list RC -> Run -> ra TSV (tự copy) để dán vào
  //  APP bước 3 (ô "dán tay"). Đọc cố định: khớp thirdTicketId -> cctsTicketStatus + occurrenceTime
  //  (hạn 48h tính từ lúc SỰ CỐ XẢY RA, không phải lúc ticket CCTS được tạo).
  // ============================================================

  const API = 'https://cloud.cnpowercore.com:8091/ccts/cctsTicket/findCCTSTicket';
  const FIELD_DEFAULT = 'thirdTicketId';   // field lọc theo External Ticket ID (RC)
  const TZ = 420;                          // UTC+7
  const DELAY = 150;
  const TSV_HEADERS = ['External Ticket ID (query)', 'Matched Ext ID', 'Ticket Status',
                       'Occurrence Time', 'Rows Found', 'Matched?', 'Note'];

  const PANEL_ID = 'ccts-fetch-panel', STYLE_ID = 'ccts-fetch-style';
  document.getElementById(PANEL_ID)?.remove();
  document.getElementById(STYLE_ID)?.remove();

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, '').toUpperCase();
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

  // ----- token: storage trước, rồi hook request -----
  let TOKEN = null, refreshTok = null;
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
  TOKEN = scanStorage();
  if (TOKEN) window.__cctsToken = TOKEN;

  if (!window.__cctsFetchHook) {
    window.__cctsFetchHook = true;
    const catchTok = (url, body) => {
      try {
        if (!/\/ccts\//i.test(url || '') || window.__cctsSelf || typeof body !== 'string') return;
        const t = deepFindToken(JSON.parse(body));
        if (t) { TOKEN = t; window.__cctsToken = t; if (refreshTok) refreshTok(); }
      } catch (e) {}
    };
    const _f = window.fetch;
    window.fetch = function (input, init) {
      try { catchTok(typeof input === 'string' ? input : (input && input.url) || '', init && init.body); } catch (e) {}
      return _f.apply(this, arguments);
    };
    const Xo = XMLHttpRequest.prototype.open, Xs = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) { this.__u = u; return Xo.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function (b) { catchTok(this.__u, b); return Xs.apply(this, arguments); };
  }

  // ----- gọi API cho 1 RC (trong tab -> credentials:'include' -> không 511) -----
  async function fetchOne(rc, field) {
    const body = JSON.stringify({ page: { pageNum: 1, pageSize: 10 }, timezoneOffset: TZ, [field]: rc, token: TOKEN });
    window.__cctsSelf = true;
    let r;
    try {
      r = await fetch(API, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json;charset=utf-8', 'Accept': 'application/json, text/plain, */*' },
        body,
      });
    } finally { window.__cctsSelf = false; }
    if (r.status === 401 || r.status === 403) { const e = new Error('HTTP ' + r.status); e.fatal = true; throw e; }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const code = String((d && d.code) != null ? d.code : '');
    if (code && code !== '200') { const e = new Error('code ' + code); e.fatal = (code === '511' || code === '401' || code === '403'); e.code = code; throw e; }
    const items = (d && d.data && d.data.list) || [];
    const hit = items.find((it) => norm(it.thirdTicketId) === norm(rc)) || null;
    return {
      query: rc,
      extId: hit ? (hit.thirdTicketId || '') : '',
      status: hit ? (hit.cctsTicketStatus || '(trống)') : (items.length ? 'Không khớp mã' : 'Không có dữ liệu'),
      occurrenceTime: hit ? (hit.occurrenceTime || hit.createTime || '') : '',
      rows: items.length,
      matched: hit ? 'YES' : 'NO',
      note: hit ? '' : (items.length ? items.length + ' record không khớp ' + field : 'không tìm thấy'),
    };
  }

  function toTSV(rows) {
    const cell = (v) => String(v == null ? '' : v).replace(/[\t\r\n]+/g, ' ').trim();
    const lines = [TSV_HEADERS.join('\t')];
    rows.forEach((r) => lines.push([r.query, r.extId, r.status, r.occurrenceTime, r.rows, r.matched, r.note].map(cell).join('\t')));
    return lines.join('\n');
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); return true; }
    catch (e) {
      try { const a = document.createElement('textarea'); a.value = t; a.style.cssText = 'position:fixed;top:-1000px;opacity:0'; document.body.appendChild(a); a.focus(); a.select(); const ok = document.execCommand('copy'); a.remove(); return ok; }
      catch (_) { return false; }
    }
  }

  // ----- UI -----
  const style = document.createElement('style'); style.id = STYLE_ID;
  style.textContent = `
  #${PANEL_ID}{position:fixed;top:16px;right:16px;z-index:2147483000;width:320px;background:#fff;border:1px solid #dcdfe6;border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,.18);font:13px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#303133}
  #${PANEL_ID} .h{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #eee}
  #${PANEL_ID} .h b{flex:1}
  #${PANEL_ID} .h button{background:transparent;border:0;font-size:16px;cursor:pointer;color:#909399;line-height:1}
  #${PANEL_ID} .bd{padding:12px}
  #${PANEL_ID} textarea{width:100%;height:96px;box-sizing:border-box;font-family:monospace;font-size:12px;padding:6px;border:1px solid #dcdfe6;border-radius:6px}
  #${PANEL_ID} .fld{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:12px;color:#606266}
  #${PANEL_ID} .fld input{flex:1;padding:4px 6px;border:1px solid #dcdfe6;border-radius:6px;font-size:12px}
  #${PANEL_ID} .btn{display:block;width:100%;border:0;border-radius:6px;padding:8px 10px;margin-top:8px;cursor:pointer;font-size:13px;font-weight:600}
  #${PANEL_ID} .p{background:#409eff;color:#fff}
  #${PANEL_ID} .g{background:#f2f3f5;color:#606266}
  #${PANEL_ID} .st{font-size:12px;color:#909399;min-height:16px;margin-top:8px}
  #${PANEL_ID} .tok{font-size:12px;margin-top:4px}
  `;
  document.head.appendChild(style);

  const panel = document.createElement('div'); panel.id = PANEL_ID;
  panel.innerHTML = `
    <div class="h"><b>CCTS — Lấy status (trong tab)</b><button data-x="close" title="Đóng">×</button></div>
    <div class="bd">
      <textarea placeholder="Dán list RC (mỗi mã 1 dòng) — copy từ app bước 1"></textarea>
      <div class="fld">Field lọc <input data-x="field" value="${FIELD_DEFAULT}"></div>
      <div class="tok"></div>
      <button class="btn p" data-x="run">▶ Lấy status</button>
      <button class="btn g" data-x="copy" disabled>📋 Copy TSV (dán vào app)</button>
      <div class="st">Sẵn sàng.</div>
    </div>`;
  document.body.appendChild(panel);
  const $ = (s) => panel.querySelector(s);
  const ta = $('textarea'), fieldEl = $('[data-x="field"]'), tokEl = $('.tok'),
        btnRun = $('[data-x="run"]'), btnCopy = $('[data-x="copy"]'), stt = $('.st');
  $('[data-x="close"]').onclick = () => panel.remove();

  let lastTSV = '';
  refreshTok = () => {
    tokEl.innerHTML = TOKEN
      ? '<span style="color:#16a34a">● Có token</span>'
      : '<span style="color:#d9820a">● Chưa có token — bấm Search 1 lần trên trang</span>';
  };
  refreshTok();

  btnCopy.onclick = async () => {
    if (!lastTSV) return;
    stt.textContent = (await copyText(lastTSV)) ? '✓ Đã copy TSV — dán vào app bước 3.' : '✗ Copy lỗi.';
  };

  btnRun.onclick = async () => {
    if (!TOKEN) { stt.innerHTML = '<span style="color:#d9820a">Chưa có token. Bấm Search 1 lần trên trang rồi Run lại.</span>'; return; }
    const list = [...new Set(ta.value.split(/[\n,]/).map((s) => s.trim()).filter(Boolean))];
    if (!list.length) { stt.textContent = 'Chưa có mã nào.'; return; }
    const field = (fieldEl.value || FIELD_DEFAULT).trim() || FIELD_DEFAULT;
    btnRun.disabled = true; btnCopy.disabled = true;
    const out = []; let matched = 0;
    for (let i = 0; i < list.length; i++) {
      stt.textContent = `Đang lấy ${i + 1}/${list.length}: ${list[i]}`;
      try {
        const res = await fetchOne(list[i], field);
        if (res.matched === 'YES') matched++;
        out.push(res);
      } catch (e) {
        out.push({ query: list[i], extId: '', status: e.code === '511' ? 'LỖI 511' : 'LỖI', occurrenceTime: '', rows: 0, matched: 'N/A', note: String(e.message || e) });
        if (e.fatal) { stt.innerHTML = `<span style="color:#d9820a">Dừng: ${e.message}. ${e.code === '511' ? 'Lạ — trong tab không nên 511; thử F5 đăng nhập lại.' : 'F5 đăng nhập lại.'}</span>`; break; }
      }
      await sleep(DELAY);
    }
    lastTSV = toTSV(out);
    window.__cctsTSV = lastTSV;
    const auto = await copyText(lastTSV);
    btnRun.disabled = false; btnCopy.disabled = false;
    stt.innerHTML = `Xong ${out.length} mã — khớp ${matched}. ${auto ? '<b>Đã copy TSV</b>, dán vào app bước 3.' : 'Bấm "Copy TSV".'}`;
  };

  console.log('[CCTS in-tab] Panel đã mở. Dán list RC -> Lấy status. TSV cũng ở window.__cctsTSV');
})();

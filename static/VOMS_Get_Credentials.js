(function () {
  function tok(){ for(const s of [localStorage,sessionStorage]) for(let i=0;i<s.length;i++){ const m=(s.getItem(s.key(i))||'').match(/eyJ[\w-]+\.[\w-]+\.[\w-]+/); if(m) return m[0]; } return null; }
  const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const TIDKEY=/^(tid|tenantid|tenant_id|x-tenant-id|currenttenantid|activetenantid)$/i;
  function deep(o,d){ d=d||0; if(!o||typeof o!=='object'||d>6) return null;
    for(const k of Object.keys(o)){ const v=o[k];
      if(TIDKEY.test(k)&&(typeof v==='string'||typeof v==='number')&&String(v).trim()) return String(v).trim();
      if(/tenant/i.test(k)&&typeof v==='string'&&UUID.test(v.trim())) return v.trim();
      if(v&&typeof v==='object'){ const r=deep(v,d+1); if(r) return r; } }
    return null; }
  function fromStorage(){ for(const s of [localStorage,sessionStorage]) for(let i=0;i<s.length;i++){ const k=s.key(i),raw=s.getItem(k)||'';
      if(/tenant/i.test(k)&&UUID.test(raw.trim())) return raw.trim();
      try{ const r=deep(JSON.parse(raw)); if(r) return r; }catch(e){}
      const m=raw.match(/"(?:tid|tenantId|tenant_id|tenantid)"\s*:\s*"([^"]+)"/i); if(m) return m[1];
    } return null; }
  function fromJwt(t){ try{ const p=t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'); return deep(JSON.parse(decodeURIComponent(escape(atob(p))))); }catch(e){ return null; } }
  const t=tok(); const tid=(window.__hdr&&window.__hdr['X-Tenant-Id'])||fromStorage()||(t&&fromJwt(t))||null;
  console.log('%cBearer token:','font-weight:bold', t||'(không thấy trong storage)');
  console.log('%cX-Tenant-Id:','font-weight:bold', tid||'(không tự tìm được — lấy tay ở Network)');
})();
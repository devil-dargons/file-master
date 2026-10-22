# === 文件路径: src/server/web_page.py ===
"""LAN 服务的单页前端（移动端三抽屉：左筛选 / 底部标签 / 右详情）。

内嵌为字符串常量，避免 PyInstaller 打包时的数据文件问题。
"""

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>FileMaster LAN</title>
<style>
  :root {
    --bg:#1e1f22; --surface:#26282c; --surface-alt:#2f3237; --surface-hover:#3a3d44;
    --border:#3a3d42; --text:#dfe1e5; --text-muted:#9aa0a6;
    --accent:#4c8dff; --accent-text:#fff; --success:#3fb950; --danger:#e5534b;
  }
  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  html,body { height:100%; background:var(--bg); color:var(--text);
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; overflow:hidden; }
  button { font-family:inherit; cursor:pointer; }
  input,select { font-family:inherit; background:var(--surface-alt); color:var(--text);
    border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-size:14px; width:100%; }
  input:focus,select:focus { outline:none; border-color:var(--accent); }

  /* ===== 登录层 ===== */
  #login-view { position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
    background:var(--bg); z-index:100; }
  #login-box { width:min(86vw,340px); background:var(--surface); border:1px solid var(--border);
    border-radius:12px; padding:28px 22px; text-align:center; }
  #login-box h2 { font-size:18px; margin-bottom:6px; }
  #login-box .hint { color:var(--text-muted); font-size:12px; margin-bottom:18px; }
  #login-box input { margin-bottom:12px; text-align:center; }
  #login-box button { width:100%; padding:10px; border:none; border-radius:6px;
    background:var(--accent); color:var(--accent-text); font-size:15px; }
  #login-err { color:var(--danger); font-size:12px; margin-top:10px; min-height:16px; }

  /* ===== 主视图 ===== */
  #main-view { position:fixed; inset:0; display:none; flex-direction:column; }
  #topbar { height:40px; flex:none; display:flex; align-items:center; justify-content:space-between;
    padding:0 10px; background:var(--surface); border-bottom:1px solid var(--border); font-size:13px; }
  #topbar .counter { color:var(--text-muted); }
  #topbar .counter input { width:64px; padding:2px 6px; text-align:center; font-size:13px; }

  #stage { flex:1; position:relative; overflow:hidden; touch-action:none; }
  #stage img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain;
    will-change:transform; }
  #stage .empty { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
    color:var(--text-muted); font-size:14px; text-align:center; padding:20px; }

  .nav-btn { position:absolute; top:50%; transform:translateY(-50%); z-index:5;
    width:42px; height:64px; border:none; border-radius:8px;
    background:rgba(58,61,68,.55); color:var(--text); font-size:22px; }
  .nav-btn:active { background:rgba(90,94,104,.75); }
  #btn-prev { left:8px; } #btn-next { right:8px; }

  #filename-bar { flex:none; padding:6px 12px; background:var(--surface);
    border-top:1px solid var(--border); font-size:12px; color:var(--text-muted);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

  /* ===== 抽屉通用手柄（屏幕边缘小方块） ===== */
  .drawer-handle { position:fixed; z-index:30; width:26px; height:56px; border:none;
    background:var(--surface-alt); border:1px solid var(--border); color:var(--text-muted);
    font-size:11px; writing-mode:vertical-lr; letter-spacing:2px;
    display:flex; align-items:center; justify-content:center; }
  #handle-filter { left:0; top:38%; border-radius:0 8px 8px 0; border-left:none; }
  #handle-detail { right:0; top:38%; width:26px; height:56px; border-radius:8px 0 0 8px; border-right:none; }
  #handle-tags { left:50%; transform:translateX(-50%); bottom:0; width:56px; height:22px;
    writing-mode:horizontal-tb; letter-spacing:1px; border-radius:8px 8px 0 0; border-bottom:none; }

  /* ===== 抽屉 ===== */
  .drawer { position:fixed; z-index:40; background:var(--surface); transition:transform .22s ease-out;
    display:flex; flex-direction:column; }
  /* 左侧：条件筛选 */
  #drawer-filter { left:0; top:0; bottom:0; width:min(82vw,320px);
    border-right:1px solid var(--border); transform:translateX(-100%); }
  #drawer-filter.open { transform:translateX(0); }
  /* 右侧：详情 */
  #drawer-detail { right:0; top:0; bottom:0; width:min(82vw,320px);
    border-left:1px solid var(--border); transform:translateX(100%); }
  #drawer-detail.open { transform:translateX(0); }
  /* 底部：标签（最高屏幕三分之一，标签过多时内容区内滚动） */
  #drawer-tags { left:0; right:0; bottom:0; max-height:33.33vh;
    border-top:1px solid var(--border); transform:translateY(100%); }
  #drawer-tags.open { transform:translateY(0); }

  /* 遮罩层：筛选/详情抽屉打开时，点击抽屉以外区域关闭 */
  #drawer-mask { position:fixed; inset:0; z-index:35; background:rgba(0,0,0,.45);
    opacity:0; pointer-events:none; transition:opacity .22s; }
  #drawer-mask.show { opacity:1; pointer-events:auto; }

  .drawer-head { flex:none; display:flex; align-items:center; justify-content:space-between;
    padding:10px 12px; border-bottom:1px solid var(--border); font-weight:600; font-size:14px; }
  .drawer-head .close { background:none; border:none; color:var(--text-muted); font-size:20px; padding:0 4px; }
  .drawer-body { flex:1; overflow-y:auto; padding:12px; }
  .drawer-foot { flex:none; padding:10px 12px; border-top:1px solid var(--border);
    display:flex; gap:8px; }
  .btn-primary { flex:1; padding:9px; border:none; border-radius:6px;
    background:var(--accent); color:var(--accent-text); font-size:14px; }
  .btn-ghost { padding:9px 16px; border:1px solid var(--border); border-radius:6px;
    background:var(--surface-alt); color:var(--text); font-size:14px; }

  .field { margin-bottom:12px; }
  .field label { display:block; font-size:12px; color:var(--text-muted); margin-bottom:4px; }
  .field .row { display:flex; gap:6px; }
  .field .row select { width:74px; flex:none; }

  /* 标签 chips（流式排列，点击切换选中） */
  #tag-chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }
  .chip { padding:5px 12px; border-radius:14px; font-size:13px;
    border:1px solid var(--border); background:var(--surface-alt); color:var(--text); }
  .chip.on { background:var(--accent); border-color:var(--accent); color:var(--accent-text); }

  /* 详情键值表 */
  .kv { display:flex; font-size:13px; padding:7px 0; border-bottom:1px solid var(--border); }
  .kv .k { flex:none; width:64px; color:var(--text-muted); }
  .kv .v { flex:1; word-break:break-all; user-select:text; }

  #toast { position:fixed; left:50%; bottom:80px; transform:translateX(-50%); z-index:60;
    background:var(--surface-alt); border:1px solid var(--border); color:var(--text);
    padding:8px 18px; border-radius:20px; font-size:13px; opacity:0; transition:opacity .2s;
    pointer-events:none; }
</style>
</head>
<body>

<!-- 登录 -->
<div id="login-view">
  <div id="login-box">
    <h2>FileMaster 局域网访问</h2>
    <div class="hint">请输入主密码（未设置密码则留空，直接点确认）</div>
    <input id="pwd" type="password" placeholder="密码（可为空）" autocomplete="off">
    <button id="btn-login">进入</button>
    <div id="login-err"></div>
  </div>
</div>

<!-- 主视图 -->
<div id="main-view">
  <div id="topbar">
    <span>FileMaster</span>
    <span class="counter">
      <button id="btn-hd" style="background:var(--surface-alt);border:1px solid var(--accent);color:var(--accent);border-radius:4px;padding:2px 8px;font-size:12px;margin-right:8px;">HD</button>
      <input id="jump-input" type="number" min="1" inputmode="numeric"> / <span id="total">0</span>
    </span>
  </div>
  <div id="stage">
    <img id="photo" alt="" draggable="false">
    <div class="empty" id="empty-tip" style="display:none">没有匹配的图片<br>点左侧「筛选」调整条件</div>
    <div class="empty" id="error-tip" style="display:none">图片加载失败<br>（文件可能被其他程序占用）</div>
    <button class="nav-btn" id="btn-prev">‹</button>
    <button class="nav-btn" id="btn-next">›</button>
  </div>
  <div id="filename-bar">—</div>
</div>

<!-- 抽屉遮罩（筛选/详情打开时显示，点击关闭抽屉） -->
<div id="drawer-mask"></div>

<!-- 抽屉手柄 -->
<button class="drawer-handle" id="handle-filter">筛选</button>
<button class="drawer-handle" id="handle-detail">详情</button>
<button class="drawer-handle" id="handle-tags">标签</button>

<!-- 左抽屉：条件筛选 -->
<div class="drawer" id="drawer-filter">
  <div class="drawer-head">条件筛选 <button class="close" data-close="drawer-filter">×</button></div>
  <div class="drawer-body">
    <div class="field"><label>文件名包含</label><input id="f-name" placeholder="关键词"></div>
    <div class="field"><label>标签</label>
      <div class="row"><select id="f-tagop"><option value="contains">包含</option><option value="empty">为空</option><option value="not_empty">不为空</option></select>
      <input id="f-tags" placeholder="如 风景,精选"></div></div>
    <div class="field"><label>宽度</label>
      <div class="row"><select id="f-wop"><option value="">不限</option><option>=</option><option>&gt;</option><option>&lt;</option><option>&gt;=</option><option>&lt;=</option></select>
      <input id="f-wval" type="number" placeholder="px"></div></div>
    <div class="field"><label>高度</label>
      <div class="row"><select id="f-hop"><option value="">不限</option><option>=</option><option>&gt;</option><option>&lt;</option><option>&gt;=</option><option>&lt;=</option></select>
      <input id="f-hval" type="number" placeholder="px"></div></div>
    <div class="field"><label>宽高比（如 63:88）</label>
      <div class="row"><select id="f-aspectop"><option value="=">=</option><option value="!=">≠</option></select>
      <input id="f-aspect" placeholder="宽:高"></div></div>
  </div>
  <div class="drawer-foot">
    <button class="btn-ghost" id="btn-filter-clear">清空</button>
    <button class="btn-primary" id="btn-filter-apply">查询</button>
  </div>
</div>

<!-- 底部抽屉：标签 -->
<div class="drawer" id="drawer-tags">
  <div class="drawer-head">编辑标签 <button class="close" data-close="drawer-tags">×</button></div>
  <div class="drawer-body">
    <div id="tag-chips"></div>
    <input id="new-tags" placeholder="新标签（多个用英文逗号分隔）">
  </div>
  <div class="drawer-foot">
    <button class="btn-primary" id="btn-tags-apply">应用</button>
  </div>
</div>

<!-- 右抽屉：详情 -->
<div class="drawer" id="drawer-detail">
  <div class="drawer-head">详情 <button class="close" data-close="drawer-detail">×</button></div>
  <div class="drawer-body" id="detail-body"></div>
</div>

<div id="toast"></div>

<script>
"use strict";
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('fm_token') || '';
let ids = [], idx = 0, hdMode = true;  // 默认原图：缩略图仅 300px 宽，全屏显示太模糊
let allTags = [], curTags = new Set();

/* ---------- 工具 ---------- */
async function api(path, opts = {}) {
  opts.headers = Object.assign({'Authorization': 'Bearer ' + token}, opts.headers);
  if (opts.json !== undefined) {
    opts.method = opts.method || 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, opts);
  if (r.status === 401) { showLogin(); throw new Error('unauthorized'); }
  return r;
}
function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.style.opacity = 1;
  setTimeout(() => t.style.opacity = 0, 1600);
}
function showLogin() { $('login-view').style.display = 'flex'; $('main-view').style.display = 'none'; }
function showMain() { $('login-view').style.display = 'none'; $('main-view').style.display = 'flex'; }

/* ---------- 登录 ---------- */
async function login() {
  const r = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({password: $('pwd').value})});
  const d = await r.json();
  if (d.ok) {
    token = d.token; sessionStorage.setItem('fm_token', token);
    showMain(); init();
  } else {
    $('login-err').textContent = '密码错误';
  }
}
$('btn-login').onclick = login;
$('pwd').addEventListener('keydown', e => { if (e.key === 'Enter') login(); });

/* ---------- 抽屉 ---------- */
const MASKED_DRAWERS = ['drawer-filter', 'drawer-detail'];  // 带遮罩、点外部可关闭
function syncMask() {
  const open = MASKED_DRAWERS.some(id => $(id).classList.contains('open'));
  $('drawer-mask').classList.toggle('show', open);
}
function toggleDrawer(id) { $(id).classList.toggle('open'); syncMask(); }
function closeDrawer(id) { $(id).classList.remove('open'); syncMask(); }
$('handle-filter').onclick = () => { $('drawer-detail').classList.remove('open'); toggleDrawer('drawer-filter'); };
$('handle-detail').onclick = () => { $('drawer-filter').classList.remove('open'); toggleDrawer('drawer-detail');
  if ($('drawer-detail').classList.contains('open')) loadDetail(); };
$('handle-tags').onclick = () => { toggleDrawer('drawer-tags'); if ($('drawer-tags').classList.contains('open')) loadTags(); };
document.querySelectorAll('.drawer .close').forEach(b => b.onclick = () => closeDrawer(b.dataset.close));
$('drawer-mask').onclick = () => MASKED_DRAWERS.forEach(closeDrawer);

/* ---------- 查询 ---------- */
function collectFilters() {
  const f = {};
  const v = (id) => $(id).value.trim();
  if (v('f-name')) f.file_name = v('f-name');
  const tagMode = $('f-tagop').value;
  if (tagMode === 'contains') {
    if (v('f-tags')) f.tag_names = v('f-tags').split(',').map(s=>s.trim()).filter(Boolean);
  } else {
    f.tag_mode = tagMode;   // empty：标签为空；not_empty：有标签
  }
  if (v('f-wop') && v('f-wval')) { f.width_op = v('f-wop'); f.width_val = +v('f-wval'); }
  if (v('f-hop') && v('f-hval')) { f.height_op = v('f-hop'); f.height_val = +v('f-hval'); }
  const a = v('f-aspect'), ao = $('f-aspectop').value;
  if (a && a.includes(':')) {
    const [w,h] = a.split(':').map(s=>parseInt(s.trim()));
    if (w>0 && h>0) { f.aspect_w = w; f.aspect_h = h; if (ao === '!=') f.aspect_op = '!='; }
  }
  return f;
}
async function runQuery(keepIndex) {
  const r = await api('/api/query', {json: collectFilters()});
  const d = await r.json();
  ids = d.ids; idx = 0;
  $('total').textContent = ids.length;
  $('jump-input').value = ids.length ? 1 : 0;
  renderCurrent();
  closeDrawer('drawer-filter');
}
$('btn-filter-apply').onclick = () => runQuery();
$('btn-filter-clear').onclick = () => {
  ['f-name','f-tags','f-wval','f-hval','f-aspect'].forEach(i => $(i).value = '');
  $('f-wop').value = ''; $('f-hop').value = '';
  $('f-tagop').value = 'contains'; $('f-aspectop').value = '=';
  $('f-tags').disabled = false;
  runQuery();
};
// 标签为“为空/不为空”时无需输入标签文字
$('f-tagop').onchange = () => { $('f-tags').disabled = $('f-tagop').value !== 'contains'; };

/* ---------- 浏览 ---------- */
let photoUrl = null;
/* 缩放/平移状态：transform = translate(tx,ty) scale(scale)，锚点为 stage 中心 */
let scale = 1, tx = 0, ty = 0;
function applyTransform() {
  $('photo').style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
}
function resetView() { scale = 1; tx = 0; ty = 0; applyTransform(); }
function zoomAt(px, py, newScale) {  // px,py：相对 stage 中心的偏移
  newScale = Math.min(8, Math.max(1, newScale));
  const k = newScale / scale;
  tx = px - (px - tx) * k;
  ty = py - (py - ty) * k;
  scale = newScale;
  if (scale <= 1) { scale = 1; tx = 0; ty = 0; }
  applyTransform();
}
function stageCenterOffset(clientX, clientY) {
  const rect = $('stage').getBoundingClientRect();
  return [clientX - (rect.left + rect.width / 2), clientY - (rect.top + rect.height / 2)];
}
function doubleTapToggle(px, py) {  // 双击：已放大则恢复最佳大小，未放大则局部放大
  if (!ids.length) return;
  if (scale > 1) resetView();
  else zoomAt(px, py, 2.5);
}
async function render() {
  const img = $('photo');
  $('error-tip').style.display = 'none';
  resetView();
  if (photoUrl) { URL.revokeObjectURL(photoUrl); photoUrl = null; }
  if (!ids.length) { img.removeAttribute('src'); $('empty-tip').style.display='flex';
    $('filename-bar').textContent = '—'; return; }
  $('empty-tip').style.display='none';
  const id = ids[idx];
  // <img> 无法携带 Authorization 头，改用 fetch 取 blob 再生成对象 URL
  // 默认加载缩略图（快、不被第三方程序锁定）；HD 模式加载原图
  const ir = await api('/api/image/' + id + (hdMode ? '?full=1' : ''));
  if (ids[idx] !== id) return;  // 等待期间已翻页，丢弃本次结果
  if (!ir.ok) { img.removeAttribute('src'); $('error-tip').style.display = 'flex'; return; }
  photoUrl = URL.createObjectURL(await ir.blob());
  img.src = photoUrl;
  const r = await api('/api/file/' + id);
  const f = await r.json();
  $('filename-bar').textContent = f.name + (f.width ? `  ${f.width}×${f.height}` : '');
  $('jump-input').value = idx + 1;
  // 换图后刷新已打开的抽屉，避免仍显示上一张图的内容
  if ($('drawer-tags').classList.contains('open')) loadTags();
  if ($('drawer-detail').classList.contains('open')) loadDetail();
}
$('photo').onerror = () => {
  $('photo').removeAttribute('src');
  $('error-tip').style.display = 'flex';
};
$('btn-hd').onclick = () => {
  hdMode = !hdMode;
  $('btn-hd').style.color = hdMode ? 'var(--accent)' : 'var(--text-muted)';
  $('btn-hd').style.borderColor = hdMode ? 'var(--accent)' : 'var(--border)';
  render();
};
function renderCurrent() { render(); }
function go(delta) {
  if (!ids.length) return;
  idx = (idx + delta + ids.length) % ids.length;  // 循环
  render();
}
$('btn-prev').onclick = () => go(-1);
$('btn-next').onclick = () => go(1);
$('jump-input').addEventListener('change', () => {
  const n = parseInt($('jump-input').value);
  if (n >= 1 && n <= ids.length) { idx = n - 1; render(); }
  else $('jump-input').value = idx + 1;
});
/* 触摸手势：单指滑动翻页（未放大时）/ 单指平移（放大后）/ 双指缩放 / 双击复位 */
let tState = null, lastTap = {t: 0, x: 0, y: 0};
const stage = $('stage');
stage.addEventListener('touchstart', e => {
  if (e.touches.length === 1) {
    const t = e.touches[0];
    tState = {mode: scale > 1 ? 'pan' : 'swipe', x: t.clientX, y: t.clientY, tx, ty};
  } else if (e.touches.length >= 2) {
    const [a, b] = e.touches;
    tState = {mode: 'pinch', dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), scale};
  }
}, {passive:true});
stage.addEventListener('touchmove', e => {
  if (!tState) return;
  if (tState.mode === 'pinch' && e.touches.length >= 2) {
    e.preventDefault();
    const [a, b] = e.touches;
    const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    const [mx, my] = stageCenterOffset((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
    const newScale = Math.min(8, Math.max(1, tState.scale * dist / tState.dist));
    const k = newScale / scale;
    tx = mx - (mx - tx) * k;
    ty = my - (my - ty) * k;
    scale = newScale;
    applyTransform();
  } else if (tState.mode === 'pan' && e.touches.length === 1) {
    e.preventDefault();
    const t = e.touches[0];
    tx = tState.tx + t.clientX - tState.x;
    ty = tState.ty + t.clientY - tState.y;
    applyTransform();
  }
}, {passive:false});
stage.addEventListener('touchend', e => {
  if (!tState) return;
  if (tState.mode === 'pinch') {
    if (e.touches.length > 0) {  // 剩一指：转为平移
      const t = e.touches[0];
      tState = {mode: 'pan', x: t.clientX, y: t.clientY, tx, ty};
    } else {
      if (scale <= 1.05) resetView();
      tState = null;
    }
    return;
  }
  const t = e.changedTouches[0];
  if (tState.mode === 'swipe') {
    const dx = t.clientX - tState.x, dy = t.clientY - tState.y;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
      go(dx < 0 ? 1 : -1);
      lastTap = {t: 0, x: 0, y: 0};
    } else if (Math.abs(dx) < 10 && Math.abs(dy) < 10) {
      const now = Date.now();  // 双击检测
      if (now - lastTap.t < 300 && Math.hypot(t.clientX - lastTap.x, t.clientY - lastTap.y) < 40) {
        doubleTapToggle(...stageCenterOffset(t.clientX, t.clientY));
        lastTap = {t: 0, x: 0, y: 0};
      } else {
        lastTap = {t: now, x: t.clientX, y: t.clientY};
      }
    }
  }
  if (scale <= 1.05) resetView();
  tState = null;
}, {passive:true});
/* 鼠标：滚轮缩放 / 按住拖动（放大后）/ 双击复位 */
stage.addEventListener('wheel', e => {
  if (!ids.length) return;
  e.preventDefault();
  zoomAt(...stageCenterOffset(e.clientX, e.clientY), scale * (e.deltaY < 0 ? 1.25 : 0.8));
}, {passive:false});
let mouseDrag = null;
stage.addEventListener('mousedown', e => {
  if (scale <= 1 || e.button !== 0) return;
  mouseDrag = {x: e.clientX, y: e.clientY, tx, ty};
  e.preventDefault();
});
window.addEventListener('mousemove', e => {
  if (!mouseDrag) return;
  tx = mouseDrag.tx + e.clientX - mouseDrag.x;
  ty = mouseDrag.ty + e.clientY - mouseDrag.y;
  applyTransform();
});
window.addEventListener('mouseup', () => mouseDrag = null);
stage.addEventListener('dblclick', e => doubleTapToggle(...stageCenterOffset(e.clientX, e.clientY)));
/* 键盘（接显示器的场景） */
document.addEventListener('keydown', e => {
  if ($('login-view').style.display !== 'none') return;
  if (e.key === 'ArrowLeft') go(-1);
  if (e.key === 'ArrowRight') go(1);
});

/* ---------- 标签 ---------- */
async function loadTags() {
  if (!ids.length) return;
  const fid = ids[idx];
  const [rAll, rCur] = await Promise.all([api('/api/tags'), api('/api/file/' + fid + '/tags')]);
  if (ids[idx] !== fid) return;  // 请求期间已翻页，丢弃过期结果
  allTags = (await rAll.json()).tags;
  curTags = new Set((await rCur.json()).tags);
  renderChips();
}
function renderChips() {
  const box = $('tag-chips'); box.innerHTML = '';
  allTags.forEach(t => {
    const b = document.createElement('button');
    b.className = 'chip' + (curTags.has(t) ? ' on' : '');
    b.textContent = t;
    b.onclick = () => { curTags.has(t) ? curTags.delete(t) : curTags.add(t); b.classList.toggle('on'); };
    box.appendChild(b);
  });
}
$('btn-tags-apply').onclick = async () => {
  if (!ids.length) return;
  const add = [...curTags];
  $('new-tags').value.split(',').map(s=>s.trim()).filter(Boolean).forEach(t => add.push(t));
  const remove = allTags.filter(t => !curTags.has(t));
  const r = await api('/api/file/' + ids[idx] + '/tags', {json: {add, remove}});
  const d = await r.json();
  if (d.ok) { $('new-tags').value = ''; toast('标签已更新'); loadTags(); }
  else toast('更新失败');
};

/* ---------- 详情 ---------- */
async function loadDetail() {
  if (!ids.length) { $('detail-body').innerHTML = ''; return; }
  const fid = ids[idx];
  const r = await api('/api/file/' + fid);
  const f = await r.json();
  if (ids[idx] !== fid) return;  // 请求期间已翻页，丢弃过期结果
  const rows = [
    ['名称', f.name], ['路径', f.path],
    ['大小', f.size_text], ['宽高', f.width ? f.width + ' × ' + f.height : '-'],
    ['类型', f.file_type], ['MD5', f.md5 || '-'],
    ['修改时间', f.mtime_text], ['入库时间', f.added_text],
    ['标签', f.tags.length ? f.tags.join('、') : '-'],
  ];
  $('detail-body').innerHTML = rows.map(([k,v]) =>
    `<div class="kv"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
}

/* ---------- 初始化 ---------- */
async function init() { await runQuery(); }
if (token) { showMain(); init(); }
</script>
</body>
</html>
"""

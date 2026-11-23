/* ============================================================
   单证一致性智能体 · 站点交互
   所有数据均来自同源 FastAPI 接口，不写死业务数字
   ============================================================ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var resultBox = $('resultBox');
  var endpointLabel = $('endpointLabel');

  /* HTML 转义：接口数据来自数据库，展示前必须转义，防止注入 */
  function esc(value) {
    if (value === null || value === undefined) return '—';
    return String(value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* 统一请求封装：返回解析后的 JSON，网络异常抛出可读错误 */
  async function request(url, options) {
    var resp = await fetch(url, options);
    var data;
    try { data = await resp.json(); }
    catch (e) { throw new Error('接口返回的不是合法 JSON（HTTP ' + resp.status + '）'); }
    if (!resp.ok && data && data.error) {
      return data; // 业务级错误也按统一结构渲染
    }
    return data;
  }

  /* 状态条：显示 ok / FORBIDDEN / NOT_FOUND 等结果 */
  function statusBar(payload, label) {
    var okFlag = payload && payload.ok === true;
    var cls = okFlag ? 'status-ok' : 'status-err';
    var text = okFlag ? '200 OK' : esc((payload.error && payload.error.code) || 'ERROR');
    var msg = okFlag ? '统一响应结构 ok / data / error' : esc((payload.error && payload.error.msg) || '请求失败');
    return '<div class="result-status"><span class="status-pill ' + cls + '">' + text + '</span>' +
      '<span>' + msg + '</span><span style="margin-left:auto;color:var(--ink-mute);font-size:11px">' + esc(label) + '</span></div>';
  }

  function emptyState(text) {
    return '<div class="empty-state"><svg viewBox="0 0 48 48" fill="none" aria-hidden="true">' +
      '<rect x="8" y="10" width="32" height="28" rx="4" stroke="currentColor" stroke-width="1.6"/>' +
      '<path d="M15 19h18M15 25h12M15 31h15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
      '</svg><p>' + esc(text) + '</p></div>';
  }

  function loadingState() {
    return '<div class="empty-state"><p>正在请求接口…</p></div>';
  }

  /* ---------- 首页统计 ---------- */
  async function loadOverview() {
    try {
      var payload = await request('/api/overview');
      if (!payload || payload.ok !== true || !payload.data) return;
      Object.keys(payload.data).forEach(function (key) {
        var el = document.querySelector('[data-stat="' + key + '"]');
        if (el) el.textContent = payload.data[key];
      });
    } catch (e) {
      // 统计条保持破折号，不让首页因可选数据失败而报错
    }
  }

  /* ---------- 权限矩阵 ---------- */
  async function loadRoles() {
    var tbody = document.querySelector('#roleTable tbody');
    try {
      var payload = await request('/api/roles');
      if (!payload || payload.ok !== true || !payload.data || !payload.data.roles) throw new Error('bad payload');
      var fields = [
        ['can_query', '查询'], ['can_submit_change', '提交变更'],
        ['can_confirm', '确认放行'], ['can_manage_queue', '管理队列'], ['can_view_audit', '查看审计']
      ];
      var html = '';
      payload.data.roles.forEach(function (role) {
        html += '<tr><td>' + esc(role.key) + '</td><td>' + esc(role.display_name || '—') + '</td>';
        fields.forEach(function (f) {
          var on = role[f[0]] === true;
          html += '<td class="' + (on ? 'yes-mark' : 'no-mark') + '">' + (on ? '允许' : '—') + '</td>';
        });
        html += '</tr>';
      });
      tbody.innerHTML = html;
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="7" class="loading-cell">权限配置读取失败，请刷新重试</td></tr>';
    }
  }

  /* ---------- 渲染单证包查询结果 ---------- */
  function renderPack(payload) {
    var html = statusBar(payload, 'GET /api/packs/{id}');
    if (!payload || payload.ok !== true) {
      resultBox.innerHTML = html + '<div class="result-content"><pre class="json-view">' + esc(JSON.stringify(payload, null, 2)) + '</pre></div>';
      return;
    }
    var data = payload.data;
    html += '<div class="result-content">';
    html += '<div class="mini-heading">固定声明</div><div class="hint" style="margin:0">' + esc(data.disclaimer) + '</div>';
    html += '<div class="mini-heading">单证与版本（' + data.documents.length + ' 份）</div>';

    data.documents.forEach(function (doc) {
      html += '<div class="doc-card"><div class="doc-head">' +
        '<span class="doc-type">' + esc(doc.doc_type) + '</span>' +
        '<span class="doc-no">' + esc(doc.doc_no) + '</span>' +
        '<span class="doc-src">来源：' + esc(doc.source_file) + '</span></div><div class="doc-body">';

      html += '<div class="kv-grid">';
      Object.keys(doc.payload || {}).forEach(function (k) {
        html += '<div class="kv"><span class="kv-k">' + esc(k) + '</span><span class="kv-v">' + esc(doc.payload[k]) + '</span></div>';
      });
      html += '</div>';

      html += '<table class="ver-table"><thead><tr><th>版本</th><th>有效期</th><th>确认状态</th><th>业务发生时间</th><th>系统接收时间</th><th>作废原因</th></tr></thead><tbody>';
      (doc.versions || []).forEach(function (v) {
        var stateCls = v.confirm_state === 'confirmed' ? 'state-confirmed' : (v.confirm_state === 'pending' ? 'state-pending' : 'state-voided');
        html += '<tr><td class="mono">' + esc(v.version_no) + '</td>' +
          '<td>' + (v.is_effective ? '有效' : '已过期') + '</td>' +
          '<td class="' + stateCls + '">' + esc(v.confirm_state) + '</td>' +
          '<td class="mono">' + esc(v.business_time || '—') + '</td>' +
          '<td class="mono">' + esc(v.system_time || '—') + '</td>' +
          '<td>' + esc(v.void_reason || '—') + '</td></tr>';
      });
      html += '</tbody></table></div></div>';
    });

    html += '<div class="mini-heading">交接记录（' + data.handovers.length + ' 条）</div>';
    if (!data.handovers.length) {
      html += '<div class="handover-item">该包暂无交接记录</div>';
    }
    data.handovers.forEach(function (h) {
      html += '<div class="handover-item"><strong>' + esc(h.node) + '</strong> · ' +
        esc(h.from_role) + ' → ' + esc(h.to_role) + ' · 版本 ' + esc(h.version_no) +
        '<div style="color:var(--ink-soft);font-size:11.5px">未结项：' + esc(h.open_items || '无') +
        ' ｜ 截止：' + esc(h.deadline || '未定') + '</div></div>';
    });
    html += '</div>';
    resultBox.innerHTML = html;
  }

  /* ---------- 渲染导入 / 审计 ---------- */
  function renderGeneric(payload, label, kind) {
    var html = statusBar(payload, label);
    html += '<div class="result-content">';
    if (payload && payload.ok === true && kind === 'import') {
      var d = payload.data || {};
      html += '<div class="mini-heading">新导入的包</div><div class="json-view">' +
        esc((d.imported_packs || []).length ? d.imported_packs.join('\n') : '（无，样本已全部存在）') + '</div>';
      html += '<div class="mini-heading">已跳过（幂等）</div><div class="json-view">' +
        esc((d.skipped_packs || []).length ? d.skipped_packs.join('\n') : '（无）') + '</div>';
    } else if (payload && payload.ok === true && kind === 'audit') {
      html += '<div class="mini-heading">审计记录（' + ((payload.data && payload.data.total) || 0) + ' 条）</div>';
      html += '<pre class="json-view">' + esc(JSON.stringify(payload.data, null, 2)) + '</pre>';
    } else {
      html += '<pre class="json-view">' + esc(JSON.stringify(payload, null, 2)) + '</pre>';
    }
    html += '</div>';
    resultBox.innerHTML = html;
  }

  /* ---------- 按钮事件 ---------- */
  function actorValue() { return $('actor').value.trim() || 'anonymous'; }
  function roleValue() { return $('roleKey').value; }

  $('btnQuery').addEventListener('click', async function () {
    var packId = $('packId').value.trim();
    if (!packId) { resultBox.innerHTML = emptyState('请先填写单证包编号'); return; }
    var url = '/api/packs/' + encodeURIComponent(packId) +
      '?actor=' + encodeURIComponent(actorValue()) + '&role_key=' + encodeURIComponent(roleValue());
    endpointLabel.textContent = 'GET ' + url;
    resultBox.innerHTML = loadingState();
    try { renderPack(await request(url)); }
    catch (e) { resultBox.innerHTML = emptyState('请求失败：' + e.message); }
  });

  $('btnImport').addEventListener('click', async function () {
    var url = '/api/import?actor=' + encodeURIComponent(actorValue());
    endpointLabel.textContent = 'POST ' + url;
    resultBox.innerHTML = loadingState();
    try { renderGeneric(await request(url, { method: 'POST' }), 'POST /api/import', 'import'); }
    catch (e) { resultBox.innerHTML = emptyState('请求失败：' + e.message); }
  });

  $('btnAudit').addEventListener('click', async function () {
    var url = '/api/audit?actor=' + encodeURIComponent(actorValue()) +
      '&role_key=' + encodeURIComponent(roleValue()) + '&limit=20';
    endpointLabel.textContent = 'GET ' + url;
    resultBox.innerHTML = loadingState();
    try { renderGeneric(await request(url), 'GET /api/audit', 'audit'); }
    catch (e) { resultBox.innerHTML = emptyState('请求失败：' + e.message); }
  });

  /* 页面初始化 */
  loadOverview();
  loadRoles();
})();

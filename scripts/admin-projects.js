/* ===== Admin 项目监管（对接 backend /projects）===== */
(function () {
  const $ = (id) => document.getElementById(id);
  const PAGE_SIZE = 15;
  let page = 1;
  let filters = { risk: "", supervision: "", status: "", q: "" };
  let current = null;

  function getToken() {
    try {
      const p = JSON.parse(localStorage.getItem("cm_auth") || "null");
      return p && p.token ? p.token : null;
    } catch (_) { return null; }
  }
  async function api(method, path, body) {
    const token = getToken();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = "Bearer " + token;
    let resp;
    try {
      resp = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    } catch (e) { return { ok: false, networkError: true, error: String(e) }; }
    let data = null;
    try { data = await resp.json(); } catch (_) {}
    if (!resp.ok) return { ok: false, status: resp.status, data, error: (data && (data.detail || data.error)) || resp.statusText };
    return { ok: true, status: resp.status, data };
  }

  const RISK_MAP = { high: ["高", "warn"], medium: ["中", "info"], low: ["低", "ok"], normal: ["正常", "default"] };
  const SUP_MAP = { priority: "重点", key: "关键", routine: "常规" };
  const ST_MAP = { active: ["在管", "ok"], suspended: ["暂停", "warn"], closed: ["已结案", "default"] };
  function tag(map, v) { const [l, c] = map[v] || [v, "default"]; return `<span class="status ${c}">${l}</span>`; }
  function fmtTs(iso) { return iso ? iso.slice(0, 19).replace("T", " ") : "—"; }
  function escapeHTML(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  async function loadList() {
    const body = $("pm-body");
    if (!body) return;
    body.innerHTML = `<tr><td colspan="8" class="muted">加载中…</td></tr>`;
    const qs = new URLSearchParams({ page: String(page), size: String(PAGE_SIZE) });
    if (filters.risk) qs.set("risk", filters.risk);
    if (filters.supervision) qs.set("supervision", filters.supervision);
    if (filters.status) qs.set("status", filters.status);
    if (filters.q) qs.set("q", filters.q);
    const res = await api("GET", "/projects?" + qs.toString());
    if (!res.ok) {
      if (res.status === 401) body.innerHTML = `<tr><td colspan="8" class="muted">未授权。<a href="login.html" class="link">重新登录</a>。</td></tr>`;
      else if (res.status === 403) body.innerHTML = `<tr><td colspan="8" class="muted">权限不足：当前角色无 project:read 权限。</td></tr>`;
      else body.innerHTML = `<tr><td colspan="8" class="muted">加载失败：${res.error || res.status}</td></tr>`;
      return;
    }
    const d = res.data;
    const c = d.counts_by_risk || {};
    $("pm-count").textContent = `共 ${d.total.toLocaleString()} 个`
      + `  ·  高风险 ${c.high || 0}  ·  中风险 ${c.medium || 0}  ·  低 ${c.low || 0}  ·  正常 ${c.normal || 0}`;
    $("pm-page").textContent = `第 ${d.page} / ${d.pages || 1} 页`;
    if (!d.items.length) {
      body.innerHTML = `<tr><td colspan="8" class="muted">暂无监管项目。点击右上"新增监管项目"从现有 tender 中挑一个加入监管。</td></tr>`;
      return;
    }
    body.innerHTML = d.items.map((p) => `
      <tr data-id="${p.id}" class="pm-row" style="cursor:pointer">
        <td><code>#${p.id}</code></td>
        <td>${escapeHTML(p.tender_name)}<br><span class="muted" style="font-size:11px">${escapeHTML(p.tender_key)}</span></td>
        <td>${escapeHTML(p.builder_name || "—")}</td>
        <td>${tag(RISK_MAP, p.risk_level)}</td>
        <td>${SUP_MAP[p.supervision_level] || p.supervision_level}</td>
        <td>${tag(ST_MAP, p.status)}</td>
        <td>${p.inspection_count}${p.last_inspection_at ? `<br><span class="muted" style="font-size:11px">${fmtTs(p.last_inspection_at)}</span>` : ""}</td>
        <td><button class="btn btn-ghost btn-sm pm-view" data-id="${p.id}">详情</button></td>
      </tr>`).join("");
    body.querySelectorAll(".pm-view").forEach((b) => b.addEventListener("click", (ev) => { ev.stopPropagation(); loadDetail(Number(b.dataset.id)); }));
    body.querySelectorAll(".pm-row").forEach((r) => r.addEventListener("click", () => loadDetail(Number(r.dataset.id))));
  }

  async function loadDetail(id) {
    $("pm-detail-panel").classList.remove("hidden");
    $("pm-new-panel").classList.add("hidden");
    $("pm-d-id").textContent = `#${id}`;
    $("pm-d-body").innerHTML = `<p class="muted">加载中…</p>`;
    $("pm-detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    const res = await api("GET", `/projects/${id}`);
    if (!res.ok) { $("pm-d-body").innerHTML = `<p class="muted">加载失败：${res.error || res.status}</p>`; return; }
    current = res.data;
    renderDetail(res.data);
  }

  function renderDetail(p) {
    $("pm-d-body").innerHTML = `
      <ul class="collect-stats">
        <li><span>项目</span><strong>${escapeHTML(p.tender_name)}<br><code>${escapeHTML(p.tender_key)}</code></strong></li>
        <li><span>承建方</span><strong>${escapeHTML(p.builder_name || "—")}</strong></li>
        <li><span>风险 / 监管 / 状态</span><strong>${tag(RISK_MAP, p.risk_level)} · ${SUP_MAP[p.supervision_level] || p.supervision_level} · ${tag(ST_MAP, p.status)}</strong></li>
        <li><span>巡检次数</span><strong>${p.inspection_count}  (last: ${fmtTs(p.last_inspection_at)})</strong></li>
      </ul>
      ${p.last_inspection_note ? `<div class="gov-subnote"><h4>最近巡检备注</h4><p style="white-space:pre-wrap">${escapeHTML(p.last_inspection_note)}</p></div>` : ""}
    `;
    $("pm-e-risk").value = p.risk_level;
    $("pm-e-sup").value = p.supervision_level;
    $("pm-e-status").value = p.status;
  }

  async function saveEdit() {
    if (!current) return;
    const body = {
      risk_level: $("pm-e-risk").value,
      supervision_level: $("pm-e-sup").value,
      status: $("pm-e-status").value,
    };
    const res = await api("PATCH", `/projects/${current.id}`, body);
    if (!res.ok) { alert(`保存失败：${res.error || res.status}`); return; }
    current = res.data;
    renderDetail(res.data);
    loadList();
  }

  async function submitInspection() {
    if (!current) return;
    const note = ($("pm-i-note").value || "").trim();
    if (!note) { alert("巡检备注不能为空"); return; }
    const res = await api("POST", `/projects/${current.id}/inspection`, { note });
    if (!res.ok) { alert(`登记失败：${res.error || res.status}`); return; }
    $("pm-i-note").value = "";
    current = res.data;
    renderDetail(res.data);
    loadList();
  }

  function openNew() {
    $("pm-new-panel").classList.remove("hidden");
    $("pm-detail-panel").classList.add("hidden");
    $("pm-new-form").reset();
    $("pm-new-feedback").textContent = "";
    $("pm-new-panel").scrollIntoView({ behavior: "smooth" });
  }

  async function submitNew(e) {
    e.preventDefault();
    const body = {
      tender_key: $("pm-n-key").value.trim(),
      tender_name: $("pm-n-name").value.trim(),
      builder_name: $("pm-n-builder").value.trim(),
      risk_level: $("pm-n-risk").value,
      supervision_level: $("pm-n-sup").value,
    };
    const res = await api("POST", "/projects", body);
    if (!res.ok) {
      $("pm-new-feedback").className = "hint muted flash-err";
      $("pm-new-feedback").textContent = `创建失败：${res.error || res.status}`;
      return;
    }
    $("pm-new-feedback").className = "hint muted flash-ok";
    $("pm-new-feedback").textContent = `已创建 #${res.data.id}`;
    setTimeout(() => {
      $("pm-new-panel").classList.add("hidden");
      page = 1; loadList(); loadDetail(res.data.id);
    }, 500);
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("pm-refresh") && $("pm-refresh").addEventListener("click", loadList);
    $("pm-new") && $("pm-new").addEventListener("click", openNew);
    $("pm-new-close") && $("pm-new-close").addEventListener("click", () => $("pm-new-panel").classList.add("hidden"));
    $("pm-new-reset") && $("pm-new-reset").addEventListener("click", () => $("pm-new-form").reset());
    $("pm-new-form") && $("pm-new-form").addEventListener("submit", submitNew);
    $("pm-prev") && $("pm-prev").addEventListener("click", () => { if (page > 1) { page--; loadList(); } });
    $("pm-next") && $("pm-next").addEventListener("click", () => { page++; loadList(); });
    $("pm-f-risk") && $("pm-f-risk").addEventListener("change", (e) => { filters.risk = e.target.value; page = 1; loadList(); });
    $("pm-f-sup") && $("pm-f-sup").addEventListener("change", (e) => { filters.supervision = e.target.value; page = 1; loadList(); });
    $("pm-f-status") && $("pm-f-status").addEventListener("change", (e) => { filters.status = e.target.value; page = 1; loadList(); });
    $("pm-d-close") && $("pm-d-close").addEventListener("click", () => $("pm-detail-panel").classList.add("hidden"));
    $("pm-e-save") && $("pm-e-save").addEventListener("click", saveEdit);
    $("pm-i-submit") && $("pm-i-submit").addEventListener("click", submitInspection);
    const q = $("pm-f-q");
    if (q) {
      let t = null;
      q.addEventListener("input", (e) => {
        clearTimeout(t);
        t = setTimeout(() => { filters.q = e.target.value.trim(); page = 1; loadList(); }, 300);
      });
    }

    document.querySelectorAll(".sidebar-link[data-section]").forEach((link) => {
      link.addEventListener("click", () => {
        if (link.dataset.section === "projects") { page = 1; loadList(); }
      });
    });
  });
})();

/* ===== Admin 申诉审核（对接 backend /appeals）===== */
(function () {
  const $ = (id) => document.getElementById(id);
  const PAGE_SIZE = 15;
  let page = 1;
  let filters = { status: "", category: "", q: "" };
  let currentId = null;

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
    } catch (e) {
      return { ok: false, networkError: true, error: String(e) };
    }
    let data = null;
    try { data = await resp.json(); } catch (_) {}
    if (!resp.ok) return { ok: false, status: resp.status, data, error: (data && (data.detail || data.error)) || resp.statusText };
    return { ok: true, status: resp.status, data };
  }

  const CATEGORY_MAP = { credit: "信用评价", qualification: "资质裁定", blacklist: "黑名单", other: "其他" };
  const STATUS_MAP = {
    submitted: ["已提交", "info"],
    under_review: ["审核中", "warn"],
    need_more: ["待补材料", "warn"],
    approved: ["已通过", "ok"],
    rejected: ["已驳回", "default"],
  };
  function stTag(v) { const [l, c] = STATUS_MAP[v] || [v, "default"]; return `<span class="status ${c}">${l}</span>`; }
  function fmtTs(iso) { return iso ? iso.slice(0, 19).replace("T", " ") : "—"; }
  function escapeHTML(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  async function loadList() {
    const body = $("ap-body");
    if (!body) return;
    body.innerHTML = `<tr><td colspan="8" class="muted">加载中…</td></tr>`;
    const qs = new URLSearchParams({ page: String(page), size: String(PAGE_SIZE) });
    if (filters.status) qs.set("status", filters.status);
    if (filters.category) qs.set("category", filters.category);
    if (filters.q) qs.set("q", filters.q);
    const res = await api("GET", "/appeals?" + qs.toString());
    if (!res.ok) {
      if (res.status === 401) body.innerHTML = `<tr><td colspan="8" class="muted">未授权。<a href="login.html" class="link">重新登录</a>。</td></tr>`;
      else if (res.status === 403) body.innerHTML = `<tr><td colspan="8" class="muted">权限不足：当前角色无 appeal:review 权限。</td></tr>`;
      else body.innerHTML = `<tr><td colspan="8" class="muted">加载失败：${res.error || res.status}</td></tr>`;
      return;
    }
    const d = res.data;
    const c = d.counts_by_status || {};
    $("ap-count").textContent = `共 ${d.total.toLocaleString()} 条`
      + `  ·  已提交 ${c.submitted || 0}  ·  审核中 ${c.under_review || 0}  ·  待补材料 ${c.need_more || 0}  ·  通过 ${c.approved || 0}  ·  驳回 ${c.rejected || 0}`;
    $("ap-page").textContent = `第 ${d.page} / ${d.pages || 1} 页`;
    if (!d.items.length) {
      body.innerHTML = `<tr><td colspan="8" class="muted">暂无申诉记录。</td></tr>`;
      return;
    }
    body.innerHTML = d.items.map((a) => {
      return `<tr data-id="${a.id}" class="ap-row" style="cursor:pointer">
        <td><code>#${a.id}</code></td>
        <td>${escapeHTML(a.enterprise_name)}<br><span class="muted" style="font-size:11px">${escapeHTML(a.enterprise_key)}</span></td>
        <td>${CATEGORY_MAP[a.category] || a.category}</td>
        <td>${escapeHTML(a.title)}</td>
        <td>${stTag(a.status)}</td>
        <td>${a.reviewer_id || "—"}</td>
        <td>${fmtTs(a.created_at)}</td>
        <td><button class="btn btn-ghost btn-sm ap-view" data-id="${a.id}">详情</button></td>
      </tr>`;
    }).join("");
    body.querySelectorAll(".ap-view").forEach((b) => b.addEventListener("click", (ev) => { ev.stopPropagation(); loadDetail(Number(b.dataset.id)); }));
    body.querySelectorAll(".ap-row").forEach((r) => r.addEventListener("click", () => loadDetail(Number(r.dataset.id))));
  }

  async function loadDetail(id) {
    currentId = id;
    $("ap-detail-panel").classList.remove("hidden");
    $("ap-new-panel").classList.add("hidden");
    $("ap-d-id").textContent = `#${id}`;
    $("ap-d-body").innerHTML = `<p class="muted">加载中…</p>`;
    $("ap-d-actions").innerHTML = "";
    $("ap-detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    const res = await api("GET", `/appeals/${id}`);
    if (!res.ok) { $("ap-d-body").innerHTML = `<p class="muted">加载失败：${res.error || res.status}</p>`; return; }
    renderDetail(res.data);
  }

  function renderDetail(a) {
    $("ap-d-body").innerHTML = `
      <ul class="collect-stats">
        <li><span>企业</span><strong>${escapeHTML(a.enterprise_name)}<br><code>${escapeHTML(a.enterprise_key)}</code></strong></li>
        <li><span>申诉类别 / 状态</span><strong>${CATEGORY_MAP[a.category] || a.category} · ${stTag(a.status)}</strong></li>
        <li><span>申诉人 / 审核人</span><strong>user #${a.appellant_user_id || "-"} / user #${a.reviewer_id || "-"}</strong></li>
        <li><span>提交 / 审核时间</span><strong>${fmtTs(a.created_at)} / ${fmtTs(a.reviewed_at)}</strong></li>
      </ul>
      <p style="padding:6px 0"><b>${escapeHTML(a.title)}</b></p>
      <p class="hint" style="white-space:pre-wrap;line-height:1.6">${escapeHTML(a.detail || "(无详情)")}</p>
      ${a.evidence_url ? `<p class="hint">证据链接：<a class="link" href="${escapeHTML(a.evidence_url)}" target="_blank" rel="noopener">${escapeHTML(a.evidence_url)}</a></p>` : ""}
      ${a.review_note ? `<div class="gov-subnote"><h4>审核意见</h4><p style="white-space:pre-wrap">${escapeHTML(a.review_note)}</p></div>` : ""}
    `;
    // 按状态机放按钮
    const allowed = {
      submitted: ["start_review"],
      under_review: ["approve", "reject", "need_more"],
      need_more: ["start_review"],
      approved: [],
      rejected: [],
    }[a.status] || [];
    const btnDef = {
      start_review: ["开始审核", "btn-primary"],
      approve: ["通过", "btn-primary"],
      reject: ["驳回", "btn-danger"],
      need_more: ["要求补材料", "btn-ghost"],
    };
    $("ap-d-actions").innerHTML = allowed.length
      ? allowed.map((k) => {
          const [l, c] = btnDef[k];
          return `<button class="btn ${c}" data-decision="${k}">${l}</button>`;
        }).join("")
      : `<span class="muted">终态（${a.status}），不可再改</span>`;
    $("ap-d-actions").querySelectorAll("button[data-decision]").forEach((b) =>
      b.addEventListener("click", () => doReview(a.id, b.dataset.decision))
    );
  }

  async function doReview(id, decision) {
    const note = ($("ap-d-note").value || "").trim();
    if ((decision === "reject" || decision === "need_more") && !note) {
      if (!confirm("未填写意见，仍然提交？")) return;
    }
    const res = await api("POST", `/appeals/${id}/review`, { decision, note });
    if (!res.ok) {
      alert(`操作失败：${res.error || res.status}`);
      return;
    }
    $("ap-d-note").value = "";
    renderDetail(res.data);
    loadList();
  }

  // ===== 代企业提交 =====
  function openNew() {
    $("ap-new-panel").classList.remove("hidden");
    $("ap-detail-panel").classList.add("hidden");
    $("ap-new-feedback").textContent = "";
    $("ap-new-form").reset();
    $("ap-new-panel").scrollIntoView({ behavior: "smooth" });
  }

  async function submitNew(e) {
    e.preventDefault();
    const body = {
      enterprise_key: $("ap-n-key").value.trim(),
      enterprise_name: $("ap-n-name").value.trim(),
      category: $("ap-n-category").value,
      title: $("ap-n-title").value.trim(),
      detail: $("ap-n-detail").value,
      evidence_url: $("ap-n-evidence").value.trim(),
    };
    const res = await api("POST", "/appeals", body);
    if (!res.ok) {
      $("ap-new-feedback").className = "hint muted flash-err";
      $("ap-new-feedback").textContent = `提交失败：${res.error || res.status}（提示：admin 账号没 appeal:submit 权限；改用 business 角色提交，或在 bootstrap.py 里给 admin 加该权限）`;
      return;
    }
    $("ap-new-feedback").className = "hint muted flash-ok";
    $("ap-new-feedback").textContent = `已提交 #${res.data.id}`;
    setTimeout(() => {
      $("ap-new-panel").classList.add("hidden");
      page = 1; loadList(); loadDetail(res.data.id);
    }, 600);
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("ap-refresh") && $("ap-refresh").addEventListener("click", loadList);
    $("ap-new") && $("ap-new").addEventListener("click", openNew);
    $("ap-new-close") && $("ap-new-close").addEventListener("click", () => $("ap-new-panel").classList.add("hidden"));
    $("ap-new-reset") && $("ap-new-reset").addEventListener("click", () => $("ap-new-form").reset());
    $("ap-new-form") && $("ap-new-form").addEventListener("submit", submitNew);
    $("ap-prev") && $("ap-prev").addEventListener("click", () => { if (page > 1) { page--; loadList(); } });
    $("ap-next") && $("ap-next").addEventListener("click", () => { page++; loadList(); });
    $("ap-f-status") && $("ap-f-status").addEventListener("change", (e) => { filters.status = e.target.value; page = 1; loadList(); });
    $("ap-f-category") && $("ap-f-category").addEventListener("change", (e) => { filters.category = e.target.value; page = 1; loadList(); });
    $("ap-d-close") && $("ap-d-close").addEventListener("click", () => $("ap-detail-panel").classList.add("hidden"));
    const q = $("ap-f-q");
    if (q) {
      let t = null;
      q.addEventListener("input", (e) => {
        clearTimeout(t);
        t = setTimeout(() => { filters.q = e.target.value.trim(); page = 1; loadList(); }, 300);
      });
    }

    document.querySelectorAll(".sidebar-link[data-section]").forEach((link) => {
      link.addEventListener("click", () => {
        if (link.dataset.section === "penalties") { page = 1; loadList(); }
      });
    });
  });
})();

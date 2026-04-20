/* ===== Admin 预警处置 =====
 * 对接 backend /alerts API（需要 alert:read + alert:write 权限）
 */
(function () {
  const $ = (id) => document.getElementById(id);
  const PAGE_SIZE = 15;
  let page = 1;
  let currentDetail = null;
  let filters = { status: "", severity: "", category: "", q: "" };

  function getToken() {
    try {
      const raw = localStorage.getItem("cm_auth");
      const p = raw ? JSON.parse(raw) : null;
      return p && p.token ? p.token : null;
    } catch (e) {
      return null;
    }
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
    try { data = await resp.json(); } catch (_) { /* no body */ }
    if (!resp.ok) return { ok: false, status: resp.status, data, error: (data && data.detail) || resp.statusText };
    return { ok: true, status: resp.status, data };
  }

  // ===== 时间格式 =====
  function fmtTs(iso) {
    if (!iso) return "-";
    return iso.slice(0, 19).replace("T", " ");
  }

  const SEVERITY_MAP = { high: ["高", "warn"], medium: ["中", "info"], low: ["低", "ok"] };
  const STATUS_MAP = {
    open: ["待处置", "warn"],
    ack: ["受理中", "info"],
    resolved: ["已处置", "ok"],
    dismissed: ["已驳回", "default"],
  };
  const CATEGORY_MAP = {
    quality: "质量", compliance: "合规", risk: "履约/资金", complaint: "投诉", other: "其他",
  };
  function sevTag(v) { const [l, c] = SEVERITY_MAP[v] || [v, "default"]; return `<span class="status ${c}">${l}</span>`; }
  function stTag(v) { const [l, c] = STATUS_MAP[v] || [v, "default"]; return `<span class="status ${c}">${l}</span>`; }

  // ===== 列表渲染 =====
  async function loadList() {
    const body = $("al-body");
    if (!body) return;
    body.innerHTML = `<tr><td colspan="8" class="muted">加载中…</td></tr>`;

    const qs = new URLSearchParams({ page: String(page), size: String(PAGE_SIZE) });
    if (filters.status) qs.set("status", filters.status);
    if (filters.severity) qs.set("severity", filters.severity);
    if (filters.category) qs.set("category", filters.category);
    if (filters.q) qs.set("q", filters.q);

    const res = await api("GET", "/alerts?" + qs.toString());
    if (!res.ok) {
      if (res.status === 401) {
        body.innerHTML = `<tr><td colspan="8" class="muted">未授权。请<a href="login.html" class="link">重新登录</a>。</td></tr>`;
      } else if (res.status === 403) {
        body.innerHTML = `<tr><td colspan="8" class="muted">权限不足：当前角色无 alert:read 权限。</td></tr>`;
      } else {
        body.innerHTML = `<tr><td colspan="8" class="muted">加载失败：${res.error || res.status}</td></tr>`;
      }
      return;
    }

    const d = res.data;
    const counts = d.counts_by_status || {};
    $("al-counts").textContent = `共 ${d.total.toLocaleString()} 条`
      + `  ·  待处置 ${counts.open || 0}  ·  受理中 ${counts.ack || 0}  ·  已处置 ${counts.resolved || 0}  ·  已驳回 ${counts.dismissed || 0}`;
    $("al-page").textContent = `第 ${d.page} / ${d.pages || 1} 页`;

    if (d.items.length === 0) {
      body.innerHTML = `<tr><td colspan="8" class="muted">暂无匹配的预警记录。</td></tr>`;
      return;
    }
    body.innerHTML = d.items.map((a) => {
      const ent = a.entity_name || a.entity_key || "-";
      return `<tr data-id="${a.id}" class="al-row" style="cursor:pointer">
        <td><code>#${a.id}</code></td>
        <td>${escapeHTML(a.title)}</td>
        <td>${CATEGORY_MAP[a.category] || a.category}</td>
        <td>${sevTag(a.severity)}</td>
        <td>${stTag(a.status)}</td>
        <td title="${escapeHTML(a.entity_type || "")}">${escapeHTML(ent)}</td>
        <td>${fmtTs(a.created_at)}</td>
        <td><button class="btn btn-ghost btn-sm al-view" data-id="${a.id}">查看</button></td>
      </tr>`;
    }).join("");

    // 点击行或查看按钮 → 详情
    body.querySelectorAll(".al-view").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        loadDetail(Number(btn.dataset.id));
      });
    });
    body.querySelectorAll(".al-row").forEach((row) => {
      row.addEventListener("click", () => loadDetail(Number(row.dataset.id)));
    });
  }

  // ===== 详情 =====
  async function loadDetail(id) {
    const panel = $("al-detail-panel");
    panel.classList.remove("hidden");
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    $("al-d-body").innerHTML = `<p class="muted">加载中…</p>`;
    $("al-d-timeline").innerHTML = "";
    $("al-d-actions").innerHTML = "";
    $("al-d-id").textContent = `#${id}`;

    const res = await api("GET", `/alerts/${id}`);
    if (!res.ok) {
      $("al-d-body").innerHTML = `<p class="muted">加载失败：${res.error || res.status}</p>`;
      return;
    }
    currentDetail = res.data;
    renderDetail(res.data);
  }

  function renderDetail(a) {
    const ent = a.entity_name
      ? `${escapeHTML(a.entity_name)}${a.entity_key ? ` (<code>${escapeHTML(a.entity_key)}</code>)` : ""}`
      : a.entity_key ? `<code>${escapeHTML(a.entity_key)}</code>` : "—";
    $("al-d-body").innerHTML = `
      <ul class="collect-stats">
        <li><span>标题</span><strong>${escapeHTML(a.title)}</strong></li>
        <li><span>类别 / 等级 / 状态</span><strong>${CATEGORY_MAP[a.category] || a.category} · ${sevTag(a.severity)} · ${stTag(a.status)}</strong></li>
        <li><span>关联实体</span><strong>${a.entity_type ? a.entity_type + " — " : ""}${ent}</strong></li>
        <li><span>来源 / 创建时间</span><strong>${escapeHTML(a.source || "-")} · ${fmtTs(a.created_at)}</strong></li>
      </ul>
      <p class="hint" style="padding-top:4px;white-space:pre-wrap;line-height:1.6">${escapeHTML(a.detail || "(无详情)")}</p>
      ${a.resolution_note ? `<div class="gov-subnote"><h4>处置结论</h4><p style="white-space:pre-wrap">${escapeHTML(a.resolution_note)}</p></div>` : ""}
    `;

    // actions timeline
    const tl = $("al-d-timeline");
    const acts = a.actions || [];
    if (!acts.length) {
      tl.innerHTML = `<li class="muted">暂无操作记录</li>`;
    } else {
      tl.innerHTML = acts.map((x) => {
        const label = ({ create: "创建", ack: "受理", resolve: "处置", dismiss: "驳回", reopen: "重开", comment: "备注" })[x.action] || x.action;
        return `<li>
          <span class="hl hl-info">${label}</span>
          ${fmtTs(x.created_at)} · actor=${x.actor_id || "-"}
          ${x.note ? `<br><span class="muted">${escapeHTML(x.note)}</span>` : ""}
        </li>`;
      }).join("");
    }

    // 可用动作按钮
    const allowed = {
      open: ["ack", "resolve", "dismiss", "comment"],
      ack: ["resolve", "dismiss", "comment"],
      resolved: ["reopen", "comment"],
      dismissed: ["reopen", "comment"],
    }[a.status] || ["comment"];
    const btnDef = {
      ack: ["受理", "btn-primary"],
      resolve: ["处置完成", "btn-primary"],
      dismiss: ["驳回", "btn-danger"],
      reopen: ["重新打开", "btn-ghost"],
      comment: ["添加备注", "btn-ghost"],
    };
    $("al-d-actions").innerHTML = allowed.map((k) => {
      const [label, cls] = btnDef[k] || [k, "btn-ghost"];
      return `<button class="btn ${cls}" data-action="${k}">${label}</button>`;
    }).join("");
    $("al-d-actions").querySelectorAll("button[data-action]").forEach((b) => {
      b.addEventListener("click", () => doAction(a.id, b.dataset.action));
    });
  }

  async function doAction(id, action) {
    const note = ($("al-d-note").value || "").trim();
    if ((action === "resolve" || action === "dismiss") && !note) {
      if (!confirm("未填写备注，仍然提交？")) return;
    }
    const res = await api("POST", `/alerts/${id}/action`, { action, note });
    if (!res.ok) {
      alert(`操作失败：${res.error || res.status}`);
      return;
    }
    $("al-d-note").value = "";
    currentDetail = res.data;
    renderDetail(res.data);
    loadList();
  }

  // ===== 新建预警 =====
  function showNew() {
    document.querySelectorAll(".admin-section").forEach((s) => s.classList.add("hidden"));
    $("secWarningsNew").classList.remove("hidden");
    $("al-new-feedback").textContent = "";
  }
  function backToList() {
    document.querySelectorAll(".admin-section").forEach((s) => s.classList.add("hidden"));
    $("secWarnings").classList.remove("hidden");
  }

  async function submitNew(e) {
    e.preventDefault();
    const body = {
      title: $("al-n-title").value.trim(),
      category: $("al-n-category").value,
      severity: $("al-n-severity").value,
      source: ($("al-n-source").value || "manual").trim(),
      detail: $("al-n-detail").value,
      entity_type: $("al-n-etype").value || null,
      entity_key: $("al-n-ekey").value.trim() || null,
      entity_name: $("al-n-ename").value.trim() || null,
    };
    if (!body.title) {
      $("al-new-feedback").textContent = "标题必填";
      $("al-new-feedback").className = "hint muted flash-err";
      return;
    }
    const res = await api("POST", "/alerts", body);
    if (!res.ok) {
      $("al-new-feedback").textContent = `创建失败：${res.error || res.status}`;
      $("al-new-feedback").className = "hint muted flash-err";
      return;
    }
    $("al-new-feedback").textContent = `创建成功：#${res.data.id}`;
    $("al-new-feedback").className = "hint muted flash-ok";
    setTimeout(() => {
      backToList();
      page = 1;
      loadList();
      loadDetail(res.data.id);
    }, 500);
  }

  // ===== 辅助 =====
  function escapeHTML(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  // ===== 初始化 =====
  document.addEventListener("DOMContentLoaded", () => {
    $("al-refresh") && $("al-refresh").addEventListener("click", loadList);
    $("al-prev") && $("al-prev").addEventListener("click", () => { if (page > 1) { page--; loadList(); } });
    $("al-next") && $("al-next").addEventListener("click", () => { page++; loadList(); });
    $("al-f-status") && $("al-f-status").addEventListener("change", (e) => { filters.status = e.target.value; page = 1; loadList(); });
    $("al-f-severity") && $("al-f-severity").addEventListener("change", (e) => { filters.severity = e.target.value; page = 1; loadList(); });
    $("al-f-category") && $("al-f-category").addEventListener("change", (e) => { filters.category = e.target.value; page = 1; loadList(); });
    const qInput = $("al-f-q");
    if (qInput) {
      let t = null;
      qInput.addEventListener("input", (e) => {
        clearTimeout(t);
        t = setTimeout(() => { filters.q = e.target.value.trim(); page = 1; loadList(); }, 300);
      });
    }
    $("al-new") && $("al-new").addEventListener("click", showNew);
    $("al-new-cancel") && $("al-new-cancel").addEventListener("click", backToList);
    $("al-new-form") && $("al-new-form").addEventListener("submit", submitNew);
    $("al-new-reset") && $("al-new-reset").addEventListener("click", () => $("al-new-form").reset());
    $("al-d-close") && $("al-d-close").addEventListener("click", () => $("al-detail-panel").classList.add("hidden"));

    // 进入预警 tab 时拉取
    document.querySelectorAll(".sidebar-link[data-section]").forEach((link) => {
      link.addEventListener("click", () => {
        if (link.dataset.section === "warnings") loadList();
      });
    });
  });
})();

/* ===== Admin 用户管理（L2 backend /users + /roles）===== */
(function () {
  const $ = (id) => document.getElementById(id);
  const PAGE_SIZE = 15;
  let page = 1;
  let roles = [];
  let editing = null;   // null = create；number = user_id
  let currentUserId = null;
  let filters = { q: "", role: "" };

  function getToken() {
    try {
      const raw = localStorage.getItem("cm_auth");
      const p = raw ? JSON.parse(raw) : null;
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
    if (resp.status === 204) return { ok: true, status: 204, data: null };
    let data = null;
    try { data = await resp.json(); } catch (_) {}
    if (!resp.ok) return { ok: false, status: resp.status, data, error: (data && (data.detail || data.error)) || resp.statusText };
    return { ok: true, status: resp.status, data };
  }

  function fmtTs(iso) { return iso ? iso.slice(0, 19).replace("T", " ") : "—"; }
  function escapeHTML(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  // ===== 拉取当前用户 + 角色列表 =====
  async function loadRoles() {
    const res = await api("GET", "/roles");
    if (res.ok && Array.isArray(res.data)) {
      roles = res.data;
      const sel1 = $("us-f-role");   // 筛选
      const sel2 = $("us-f-role-sel"); // 表单
      if (sel1) {
        sel1.innerHTML = '<option value="">全部角色</option>' +
          roles.map((r) => `<option value="${r.id}">${escapeHTML(r.name)} (${r.permissions.length})</option>`).join("");
      }
      if (sel2) {
        sel2.innerHTML = '<option value="">（无角色）</option>' +
          roles.map((r) => `<option value="${r.id}">${escapeHTML(r.name)}</option>`).join("");
      }
    }
  }

  async function loadCurrentUser() {
    const res = await api("GET", "/auth/me");
    if (res.ok) currentUserId = res.data.id;
  }

  // ===== 列表 =====
  async function loadList() {
    const body = $("us-body");
    if (!body) return;
    body.innerHTML = `<tr><td colspan="8" class="muted">加载中…</td></tr>`;

    const qs = new URLSearchParams({ page: String(page), size: String(PAGE_SIZE) });
    if (filters.q) qs.set("q", filters.q);
    const res = await api("GET", "/users?" + qs.toString());
    if (!res.ok) {
      if (res.status === 401) {
        body.innerHTML = `<tr><td colspan="8" class="muted">未授权。<a href="login.html" class="link">重新登录</a>。</td></tr>`;
      } else if (res.status === 403) {
        body.innerHTML = `<tr><td colspan="8" class="muted">权限不足：当前角色无 user:read 权限。</td></tr>`;
      } else {
        body.innerHTML = `<tr><td colspan="8" class="muted">加载失败：${res.error || res.status}</td></tr>`;
      }
      return;
    }
    const d = res.data;
    $("us-count").textContent = `共 ${d.total.toLocaleString()} 个用户`;
    $("us-page").textContent = `第 ${d.page} / ${d.pages || 1} 页`;

    // 前端再按 role 过滤（API 没实现 role filter，留 L4）
    let items = d.items;
    if (filters.role) {
      items = items.filter((u) => (u.role || {}).id === Number(filters.role));
    }
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="8" class="muted">暂无匹配记录。</td></tr>`;
      return;
    }
    body.innerHTML = items.map((u) => {
      const rn = (u.role || {}).name;
      const roleTag = rn ? `<span class="status info">${escapeHTML(rn)}</span>` : `<span class="status default">无</span>`;
      const statusTag = u.is_active ? `<span class="status ok">启用</span>` : `<span class="status warn">禁用</span>`;
      const isSelf = u.id === currentUserId ? ' <span class="hl hl-info">当前账号</span>' : "";
      return `<tr>
        <td><code>#${u.id}</code></td>
        <td>${escapeHTML(u.email)}${isSelf}</td>
        <td>${escapeHTML(u.name || "-")}</td>
        <td>${roleTag}</td>
        <td>${statusTag}</td>
        <td>${fmtTs(u.last_login_at)}</td>
        <td>${fmtTs(u.created_at)}</td>
        <td>
          <button class="btn btn-ghost btn-sm us-edit" data-id="${u.id}">编辑</button>
        </td>
      </tr>`;
    }).join("");
    body.querySelectorAll(".us-edit").forEach((b) =>
      b.addEventListener("click", () => openEdit(Number(b.dataset.id)))
    );
  }

  // ===== 表单 =====
  function openCreate() {
    editing = null;
    $("us-form-title").textContent = "添加用户";
    $("us-form").reset();
    $("us-f-pw-label").textContent = "密码 *（至少 8 位）";
    $("us-f-pw").required = true;
    $("us-f-pw-hint").textContent = "";
    $("us-f-delete").style.display = "none";
    $("us-form-panel").classList.remove("hidden");
    $("us-form-panel").scrollIntoView({ behavior: "smooth" });
  }

  async function openEdit(id) {
    editing = id;
    const res = await api("GET", `/users/${id}`);
    if (!res.ok) {
      alert(`加载失败：${res.error || res.status}`);
      return;
    }
    const u = res.data;
    $("us-form-title").textContent = `编辑用户 #${u.id}`;
    $("us-f-email").value = u.email;
    $("us-f-email").readOnly = true;    // 不允许改邮箱
    $("us-f-name").value = u.name || "";
    $("us-f-role-sel").value = (u.role || {}).id || "";
    $("us-f-active").value = u.is_active ? "true" : "false";
    $("us-f-pw").value = "";
    $("us-f-pw").required = false;
    $("us-f-pw-label").textContent = "密码（留空 = 不改）";
    $("us-f-pw-hint").textContent = "";

    if (u.id === currentUserId) {
      $("us-f-delete").style.display = "none";
    } else {
      $("us-f-delete").style.display = "";
      $("us-f-delete").onclick = () => doDelete(u.id, u.email);
    }
    $("us-form-panel").classList.remove("hidden");
    $("us-form-panel").scrollIntoView({ behavior: "smooth" });
  }

  function closeForm() {
    editing = null;
    $("us-form-panel").classList.add("hidden");
    $("us-f-email").readOnly = false;
  }

  async function submitForm(e) {
    e.preventDefault();
    const email = $("us-f-email").value.trim();
    const name = $("us-f-name").value.trim();
    const roleVal = $("us-f-role-sel").value;
    const active = $("us-f-active").value === "true";
    const pw = $("us-f-pw").value;

    if (editing == null) {
      if (!email || !pw) {
        flash("邮箱和密码必填", "err");
        return;
      }
      if (pw.length < 8) {
        flash("密码至少 8 位", "err");
        return;
      }
      const body = {
        email, name, password: pw,
        role_id: roleVal ? Number(roleVal) : null,
      };
      const res = await api("POST", "/users", body);
      if (!res.ok) {
        flash(`创建失败：${res.error || res.status}`, "err");
        return;
      }
      flash(`已创建 #${res.data.id} ${res.data.email}`, "ok");
      closeForm();
      page = 1;
      await loadList();
      return;
    }

    // 编辑
    const patch = {
      name,
      is_active: active,
      role_id: roleVal ? Number(roleVal) : 0,  // 0 → 清空
    };
    if (pw) {
      if (pw.length < 8) {
        flash("新密码至少 8 位", "err");
        return;
      }
      patch.password = pw;
    }
    const res = await api("PATCH", `/users/${editing}`, patch);
    if (!res.ok) {
      flash(`更新失败：${res.error || res.status}`, "err");
      return;
    }
    flash(`已更新 #${res.data.id}`, "ok");
    closeForm();
    await loadList();
  }

  async function doDelete(id, email) {
    if (!confirm(`确认删除用户 ${email}?  此操作不可撤销。`)) return;
    const res = await api("DELETE", `/users/${id}`);
    if (!res.ok) {
      alert(`删除失败：${res.error || res.status}`);
      return;
    }
    flash(`已删除用户 #${id}`, "ok");
    closeForm();
    await loadList();
  }

  function flash(msg, type) {
    const el = $("us-feedback");
    if (!el) return;
    el.textContent = msg;
    el.className = "hint muted " + (type === "ok" ? "flash-ok" : type === "err" ? "flash-err" : "flash-info");
    setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4000);
  }

  // ===== 初始化 =====
  document.addEventListener("DOMContentLoaded", () => {
    $("us-refresh") && $("us-refresh").addEventListener("click", loadList);
    $("us-new") && $("us-new").addEventListener("click", openCreate);
    $("us-prev") && $("us-prev").addEventListener("click", () => { if (page > 1) { page--; loadList(); } });
    $("us-next") && $("us-next").addEventListener("click", () => { page++; loadList(); });
    $("us-form") && $("us-form").addEventListener("submit", submitForm);
    $("us-form-close") && $("us-form-close").addEventListener("click", closeForm);
    $("us-f-cancel") && $("us-f-cancel").addEventListener("click", closeForm);

    const qInput = $("us-q");
    if (qInput) {
      let t = null;
      qInput.addEventListener("input", (e) => {
        clearTimeout(t);
        t = setTimeout(() => { filters.q = e.target.value.trim(); page = 1; loadList(); }, 300);
      });
    }
    $("us-f-role") && $("us-f-role").addEventListener("change", (e) => { filters.role = e.target.value; loadList(); });

    // 进入用户 tab 时拉
    document.querySelectorAll(".sidebar-link[data-section]").forEach((link) => {
      link.addEventListener("click", async () => {
        if (link.dataset.section === "users") {
          await loadRoles();
          await loadCurrentUser();
          page = 1;
          loadList();
        }
      });
    });
  });
})();

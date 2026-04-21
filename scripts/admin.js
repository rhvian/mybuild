/* ===== Admin Page Logic ===== */

const sidebarLinks = document.querySelectorAll(".sidebar-link[data-section]");
const adminSections = document.querySelectorAll(".admin-section");
const adminTitle = document.getElementById("adminTitle");

const sectionTitles = {
  overview: "采集监控",
  collect: "采集控制台",
  enterprises: "企业管理",
  warnings: "预警处置",
  penalties: "惩戒管理",
  projects: "项目监管",
  users: "用户管理",
};

sidebarLinks.forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    sidebarLinks.forEach((l) => l.classList.remove("active"));
    link.classList.add("active");

    const section = link.dataset.section;
    adminSections.forEach((sec) => {
      const secId = sec.id.replace("sec", "").toLowerCase();
      sec.classList.toggle("hidden", secId !== section);
    });

    if (adminTitle && sectionTitles[section]) {
      adminTitle.textContent = sectionTitles[section];
    }
  });
});

// 显示当前登录账号（由 auth-guard.js 在 <head> 早期注入 window.__cmAuth）
(function renderAuthedUser() {
  try {
    const user = (window.__cmAuth || {}).user;
    if (user) {
      const el = document.getElementById("adminUserName");
      if (el) el.textContent = user;
    }
  } catch (e) {
    // ignore
  }
})();


/* ===== Admin Live Data ===== */
let adminStats = null;
let entTotal = 0;
let entTotalPages = 1;
let entReqSeq = 0;

async function apiGet(path, params = {}) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && String(v) !== "") {
      qs.set(k, String(v));
    }
  });
  const url = qs.toString() ? `${path}?${qs.toString()}` : path;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function loadAdminData() {
  try {
    const data = await apiGet("/api/stats");
    adminStats = data.stats || {};
    renderOverview(adminStats);
    renderEnterpriseList();
  } catch (e) {
    console.error("admin load failed", e);
  }
}

function renderOverview(stats) {
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };
  set("a-stat-enterprise", (stats.total_enterprise || 0).toLocaleString());
  set("a-stat-staff", (stats.total_staff || 0).toLocaleString());
  set("a-stat-tender", (stats.total_tender || 0).toLocaleString());

  const runs = stats.recent_runs || [];
  if (runs.length > 0) {
    set("a-stat-run", `${runs[0].run_id.slice(0, 12)}…`);
  }

  // 最近运行表
  const runsBody = document.getElementById("a-runs-body");
  if (runsBody) {
    if (runs.length === 0) {
      runsBody.innerHTML = `<tr><td colspan="6">暂无数据</td></tr>`;
    } else {
      runsBody.innerHTML = runs.map((r) => {
        const start = (r.started_at || "").slice(0, 19).replace("T", " ");
        const end = (r.ended_at || "").slice(0, 19).replace("T", " ") || "-";
        return `<tr>
          <td><code>${r.run_id.slice(0, 16)}</code></td>
          <td>${start}</td>
          <td>${end}</td>
          <td>${(r.raw_count || 0).toLocaleString()}</td>
          <td>${(r.normalized_count || 0).toLocaleString()}</td>
          <td>${r.issue_count > 0 ? `<span class="status warn">${r.issue_count}</span>` : `<span class="status ok">0</span>`}</td>
        </tr>`;
      }).join("");
    }
  }

  // 省份分布图
  const provChart = document.getElementById("a-province-chart");
  if (provChart) {
    const rows = (stats.province_enterprise || [])
      .filter(p => p.province_code !== "000000")
      .slice(0, 15);
    const max = Math.max(...rows.map(r => r.count), 1);
    provChart.innerHTML = rows.map((p) => {
      const pct = ((p.count / max) * 100).toFixed(1);
      return `<div class="chart-bar-row"><span class="chart-label">${p.province_name}</span><div class="chart-bar" style="--w:${pct}%"><em>${p.count.toLocaleString()}</em></div></div>`;
    }).join("");
  }
}


/* ===== 企业管理分页 ===== */
const PAGE_SIZE = 20;
let entPage = 1;
let entFilter = { keyword: "", province: "" };

async function renderEnterpriseList() {
  const body = document.getElementById("a-ent-body");
  const hint = document.getElementById("a-ent-hint");
  const pageEl = document.getElementById("a-ent-page");
  if (!body) return;

  // 省份下拉填充
  const provSelect = document.getElementById("a-ent-prov");
  if (provSelect && provSelect.children.length <= 1 && adminStats) {
    const provs = (adminStats.province_enterprise || [])
      .filter((p) => p.province_code !== "000000" && p.count > 0);
    provSelect.innerHTML = '<option value="">全部省份</option>' +
      provs.map((p) => `<option value="${p.province_name}">${p.province_name}</option>`).join("");
  }

  const reqSeq = ++entReqSeq;
  try {
    const data = await apiGet("/api/enterprise", {
      page: entPage,
      size: PAGE_SIZE,
      q: entFilter.keyword.trim(),
      province: entFilter.province,
    });
    if (reqSeq !== entReqSeq) return;
    const pageData = data.items || [];
    entTotal = Number(data.total || 0);
    entTotalPages = Math.max(1, Number(data.pages || 1));
    entPage = Math.min(entPage, entTotalPages);
    const start = entTotal === 0 ? 0 : (entPage - 1) * PAGE_SIZE + 1;
    const end = entTotal === 0 ? 0 : (entPage - 1) * PAGE_SIZE + pageData.length;

    if (hint) hint.textContent = `共匹配 ${entTotal.toLocaleString()} 家企业（当前显示 ${start}-${end}）`;
    if (pageEl) pageEl.textContent = `第 ${entPage} / ${entTotalPages} 页`;

    if (pageData.length === 0) {
      body.innerHTML = `<tr><td colspan="6">没有匹配的企业</td></tr>`;
      return;
    }
    body.innerHTML = pageData.map((e) => `
      <tr>
        <td>${e.name || "-"}</td>
        <td>${e.uscc || "-"}</td>
        <td>${e.payload?.legal_person || "-"}</td>
        <td>${e.city_name || "-"}</td>
        <td><span class="status ok">${e.status || "-"}</span></td>
        <td><a href="enterprise.html?id=${encodeURIComponent(String(e.id))}" class="link">查看</a></td>
      </tr>
    `).join("");
  } catch (e) {
    if (reqSeq !== entReqSeq) return;
    if (hint) hint.textContent = "企业列表加载失败";
    if (pageEl) pageEl.textContent = "第 - / - 页";
    body.innerHTML = `<tr><td colspan="6">加载失败，请稍后重试</td></tr>`;
    console.error("enterprise list load failed", e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const search = document.getElementById("a-ent-search");
  const prov = document.getElementById("a-ent-prov");
  const prev = document.getElementById("a-ent-prev");
  const next = document.getElementById("a-ent-next");

  let timer = null;
  if (search) {
    search.addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        entFilter.keyword = e.target.value;
        entPage = 1;
        renderEnterpriseList();
      }, 200);
    });
  }
  if (prov) {
    prov.addEventListener("change", (e) => {
      entFilter.province = e.target.value;
      entPage = 1;
      renderEnterpriseList();
    });
  }
  if (prev) prev.addEventListener("click", () => { if (entPage > 1) { entPage--; renderEnterpriseList(); } });
  if (next) next.addEventListener("click", () => {
    if (entPage < entTotalPages) { entPage++; renderEnterpriseList(); }
  });
});

loadAdminData();

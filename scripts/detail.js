/* ===== Detail Tabs ===== */
const dtabs = document.querySelectorAll(".dtab");
const dpanels = document.querySelectorAll(".dpanel");

dtabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    dtabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const target = tab.dataset.panel;
    dpanels.forEach((panel) => {
      const panelId = panel.id.replace("panel", "").toLowerCase();
      panel.classList.toggle("hidden", panelId !== target);
    });
  });
});

/* ===== Live Detail Data ===== */
let detailDataCache = null;

async function loadDetailData() {
  const root = document.getElementById("detailRoot");
  if (!root) return;
  const entityType = (root.dataset.entityType || "").toLowerCase();
  const id = new URLSearchParams(window.location.search).get("id");
  if (!entityType) return;
  if (!id) {
    showDetailBanner(root, "warn", "未携带 ?id= 参数", "请从企业库 / 人员库 / 项目库通过详情链接进入，直接打开本页无法定位具体记录。");
    return;
  }

  // 优先走 /api/{entityType}/:id；API 不可用时 fallback 到 live-data.json
  let item = null;
  let data = null;
  try {
    const apiResp = await fetch(`/api/${entityType}/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (apiResp.ok) {
      const payload = await apiResp.json();
      if (payload && payload.ok && payload.item) {
        item = payload.item;
      }
    }
  } catch (_e) {
    // 控制服务不可达；静默回退
  }

  try {
    // enterprise 详情需要关联的 staff/tender 列表 —— 仍读 live-data.json 拿上下文
    // （阶段 3 再改成 /api/enterprise/:id/staff、/api/enterprise/:id/project）
    const resp = await fetch("../scripts/live-data.json", { cache: "no-store" });
    if (resp.ok) {
      data = await resp.json();
      detailDataCache = data;
      if (!item) {
        const list = data[entityType] || [];
        item = list.find((x) => String(x.id) === String(id));
      }
    } else if (!item) {
      throw new Error(`live-data.json HTTP ${resp.status}`);
    }
  } catch (err) {
    if (!item) {
      console.error(err);
      showDetailBanner(
        root,
        "error",
        "数据加载失败",
        `读取数据出错：${String(err)}。控制服务或 live-data.json 均不可用。请联系管理员或访问<a href="admin.html" class="link">采集控制台</a>。`
      );
      return;
    }
    data = data || { enterprise: [], staff: [], tender: [] };
  }

  if (!item) {
    const typeLabel = ({ enterprise: "企业", staff: "人员", tender: "项目" })[entityType] || entityType;
    showDetailBanner(
      root,
      "warn",
      `未找到 id=${id} 的${typeLabel}记录`,
      `可能原因：① id 已过期或该记录已归档 ② 本次导出的 live-data.json 采样截断（默认仅 6000 条/实体）③ URL 从外部复制后 id 值失效。建议返回 <a href="../index.html#registry" class="link">主体库</a> 重新查询。`
    );
    return;
  }

  if (entityType === "enterprise") {
    fillEnterprise(item);
    renderEnterpriseStaff(item, data);
    renderEnterpriseProjects(item, data);
  } else if (entityType === "staff") {
    fillStaff(item);
  } else if (entityType === "tender") {
    fillProject(item);
  }
}

function showDetailBanner(root, level, title, html) {
  const banner = document.createElement("section");
  banner.className = "detail-banner banner-" + (level || "info");
  banner.innerHTML = `
    <div class="banner-icon">${level === "error" ? "✕" : level === "warn" ? "!" : "i"}</div>
    <div class="banner-body">
      <h3>${title}</h3>
      <p>${html}</p>
    </div>
  `;
  // 插到 breadcrumb 之后、业务内容之前
  const firstSection = root.querySelector("section");
  if (firstSection && firstSection.parentNode) {
    firstSection.parentNode.insertBefore(banner, firstSection);
  } else {
    root.appendChild(banner);
  }
}

function renderEnterpriseStaff(ent, data) {
  const panel = document.getElementById("panelStaff");
  if (!panel) return;
  const name = ent.name || "";
  const related = (data.staff || []).filter((s) => {
    const corp = s.payload?.register_corp_name || "";
    return corp === name;
  });
  if (related.length === 0) {
    panel.innerHTML = '<div class="gov-empty">暂无与该企业关联的注册人员数据（可能人员采集尚未覆盖该企业）。</div>';
    return;
  }
  const rowsHtml = related.slice(0, 500).map((s) => `
    <tr>
      <td><a class="link" href="person.html?id=${encodeURIComponent(String(s.id))}">${s.name || "-"}</a></td>
      <td>${s.payload?.register_type || "-"}</td>
      <td>${s.payload?.register_no || "-"}</td>
      <td>${s.payload?.person_id_no_masked || "-"}</td>
      <td>${s.event_date || "-"}</td>
    </tr>
  `).join("");
  panel.innerHTML = `
    <p class="hint" style="padding:6px 0">共 <b>${related.length}</b> 名已采集注册人员${related.length > 500 ? "（只显示前 500 条）" : ""}</p>
    <table class="gov-table">
      <thead>
        <tr>
          <th>姓名</th>
          <th>注册类别</th>
          <th>注册证书编号</th>
          <th>身份证（脱敏）</th>
          <th>注册日期</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function renderEnterpriseProjects(ent, data) {
  const panel = document.getElementById("panelProject");
  if (!panel) return;
  const name = ent.name || "";
  const related = (data.tender || []).filter((t) => {
    const builder = t.payload?.builder_name || "";
    return builder === name;
  });
  if (related.length === 0) {
    panel.innerHTML = '<div class="gov-empty">暂无与该企业关联的工程项目数据。</div>';
    return;
  }
  const rowsHtml = related.slice(0, 500).map((t) => `
    <tr>
      <td><a class="link" href="project.html?id=${encodeURIComponent(String(t.id))}">${t.name || "-"}</a></td>
      <td>${t.project_code || "-"}</td>
      <td>${t.payload?.project_type || "-"}</td>
      <td>${t.status || "-"}</td>
      <td>${t.event_date || "-"}</td>
    </tr>
  `).join("");
  panel.innerHTML = `
    <p class="hint" style="padding:6px 0">共 <b>${related.length}</b> 个已采集关联项目${related.length > 500 ? "（只显示前 500 条）" : ""}</p>
    <table class="gov-table">
      <thead>
        <tr>
          <th>项目名称</th>
          <th>项目编号</th>
          <th>项目类型</th>
          <th>状态</th>
          <th>登记日期</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function fillEnterprise(item) {
  fillText("entityName", item.name || "-");
  fillText("entityCode", `统一社会信用代码：${item.uscc || "-"}`);
  fillText("badgeA", item.status || "-");
  fillText("badgeB", "企业信息");
  fillText("badgeC", item.city_name || "-");
  fillText("scoreValue", "80");

  fillText("fieldName", item.name || "-");
  fillText("fieldUscc", item.uscc || "-");
  fillText("fieldLegal", item.payload?.legal_person || "-");
  fillText("fieldRegion", item.city_name || "-");
  fillText("fieldSourceId", item.project_code || "-");
  fillText("fieldOldCode", item.payload?.old_code || "-");
  fillText("fieldDate", item.event_date || "-");
  fillText("fieldStatus", item.status || "-");
  fillText("fieldSource", item.source_url || "-");
  renderSourceRoutes("enterprise");
}

function fillStaff(item) {
  fillText("entityName", item.name || "-");
  fillText("entityCode", `人员编码：${item.project_code || "-"}`);
  fillText("badgeA", item.status || "-");
  fillText("badgeB", item.payload?.register_type || "人员信息");
  fillText("badgeC", item.city_name || "-");
  fillText("scoreValue", "80");

  fillText("fieldName", item.name || "-");
  fillText("fieldPersonCode", item.project_code || "-");
  fillText("fieldCard", item.payload?.person_id_no_masked || "-");
  fillText("fieldRegType", item.payload?.register_type || "-");
  fillText("fieldRegNo", item.payload?.register_no || "-");

  // 注册单位：若能在 enterprise 列表里找到 id，则做成链接
  const regCorpName = item.payload?.register_corp_name || "";
  const corpEl = document.getElementById("fieldRegCorp");
  if (corpEl) {
    if (regCorpName && detailDataCache) {
      const ent = (detailDataCache.enterprise || []).find((e) => e.name === regCorpName);
      if (ent) {
        corpEl.innerHTML = `<a class="link" href="enterprise.html?id=${encodeURIComponent(String(ent.id))}">${regCorpName}</a>`;
      } else {
        corpEl.textContent = regCorpName;
      }
    } else {
      corpEl.textContent = regCorpName || "-";
    }
  }

  fillText("fieldRegion", item.city_name || "-");
  fillText("fieldDate", item.event_date || "-");
  fillText("fieldSource", item.source_url || "-");
  renderSourceRoutes("staff");
}

function fillProject(item) {
  fillText("entityName", item.name || "-");
  fillText("entityCode", `项目编号：${item.project_code || "-"}`);
  fillText("badgeA", item.status || "-");
  fillText("badgeB", item.payload?.project_type || "项目");
  fillText("badgeC", item.city_name || "-");
  fillText("scoreValue", "80");

  fillText("fieldProjectName", item.name || "-");
  fillText("fieldProjectCode", item.project_code || "-");
  fillText("fieldProjectType", item.payload?.project_type || "-");

  // 承建单位：若能在 enterprise 列表里找到 id，则做成链接
  const builderName = item.payload?.builder_name || "";
  const builderEl = document.getElementById("fieldBuilder");
  if (builderEl) {
    if (builderName && detailDataCache) {
      const ent = (detailDataCache.enterprise || []).find((e) => e.name === builderName);
      if (ent) {
        builderEl.innerHTML = `<a class="link" href="enterprise.html?id=${encodeURIComponent(String(ent.id))}">${builderName}</a>`;
      } else {
        builderEl.textContent = builderName;
      }
    } else {
      builderEl.textContent = builderName || "-";
    }
  }

  fillText("fieldDataLevel", item.payload?.data_level || "-");
  fillText("fieldIsFake", String(item.payload?.is_fake ?? "-"));
  fillText("fieldRegion", item.city_name || "-");
  fillText("fieldDate", item.event_date || "-");
  fillText("fieldSource", item.source_url || "-");
  renderSourceRoutes("project");
}

function fillText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

async function renderSourceRoutes(entityType) {
  const box = document.getElementById("sourceRoutes");
  if (!box) return;
  box.innerHTML = '<p class="hint">正在加载源站入口...</p>';
  try {
    const resp = await fetch("../scripts/source-routes.json", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const routes = data?.routes || {};
    const cat = entityType === "tender" ? "project" : entityType;
    const list = routes[cat] || [];
    if (!Array.isArray(list) || list.length === 0) {
      box.innerHTML = '<p class="hint">暂无可用源站入口</p>';
      return;
    }
    const top = list.slice(0, 12);
    box.innerHTML = top
      .map(
        (x) =>
          `<a class="source-link" href="${x.url}" target="_blank" rel="noopener noreferrer">${x.title || x.url}<span>${x.city_name || "全国"}</span></a>`
      )
      .join("");
  } catch (err) {
    box.innerHTML = `<p class="hint">源站入口加载失败：${String(err)}</p>`;
  }
}

loadDetailData();

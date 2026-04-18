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
async function loadDetailData() {
  const root = document.getElementById("detailRoot");
  if (!root) return;
  const entityType = (root.dataset.entityType || "").toLowerCase();
  const id = new URLSearchParams(window.location.search).get("id");
  if (!entityType || !id) return;

  try {
    const resp = await fetch("../scripts/live-data.json", { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const list = data[entityType] || [];
    const item = list.find((x) => String(x.id) === String(id));
    if (!item) return;

    if (entityType === "enterprise") {
      fillEnterprise(item);
    } else if (entityType === "staff") {
      fillStaff(item);
    } else if (entityType === "tender") {
      fillProject(item);
    }
  } catch (err) {
    console.error(err);
  }
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
  fillText("fieldRegCorp", item.payload?.register_corp_name || "-");
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
  fillText("fieldBuilder", item.payload?.builder_name || "-");
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

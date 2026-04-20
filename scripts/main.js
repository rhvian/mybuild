/* ===== Date & Year ===== */
const today = document.getElementById("today");
const year = document.getElementById("year");

if (today) {
  const now = new Date();
  const dateString = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
  today.textContent = dateString;
}

if (year) {
  year.textContent = String(new Date().getFullYear());
}

/* ===== Scroll Reveal ===== */
const reveals = document.querySelectorAll(".reveal");
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
      }
    });
  },
  { threshold: 0.18 }
);

reveals.forEach((node) => observer.observe(node));

/* ===== Counter Animation ===== */
const counters = document.querySelectorAll("[data-counter]");

function animateCounter(element) {
  const target = Number(element.getAttribute("data-counter") || "0");
  const duration = 1400;
  const start = performance.now();

  function tick(timestamp) {
    const progress = Math.min((timestamp - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = Math.floor(target * eased);
    element.textContent = value.toLocaleString("zh-CN");
    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  }

  requestAnimationFrame(tick);
}

const counterObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        animateCounter(entry.target);
        counterObserver.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.65 }
);

counters.forEach((el) => counterObserver.observe(el));

/* ===== Mobile Menu Toggle ===== */
const menuToggle = document.getElementById("menuToggle");
const mobileNav = document.getElementById("mobileNav");

if (menuToggle && mobileNav) {
  menuToggle.addEventListener("click", () => {
    menuToggle.classList.toggle("open");
    mobileNav.classList.toggle("open");
  });

  mobileNav.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      menuToggle.classList.remove("open");
      mobileNav.classList.remove("open");
    });
  });
}

/* ===== Nav Scroll Highlight ===== */
const mainNav = document.getElementById("mainNav");
if (mainNav) {
  const navLinks = mainNav.querySelectorAll("a[data-section]");
  const sections = document.querySelectorAll("section[id]");

  function highlightNav() {
    let current = "";
    sections.forEach((section) => {
      const top = section.offsetTop - 100;
      if (window.scrollY >= top) {
        current = section.id;
      }
    });
    navLinks.forEach((link) => {
      link.classList.toggle("active", link.dataset.section === current);
    });
  }

  window.addEventListener("scroll", highlightNav, { passive: true });
  highlightNav();
}

/* ===== Live Data Load ===== */
let liveDataCache = {
  run_id: "",
  updated_at: "",
  enterprise: [],
  staff: [],
  tender: [],
};

async function loadLiveData() {
  const liveMeta = document.getElementById("liveMeta");
  const enterpriseList = document.getElementById("enterpriseList");
  const staffList = document.getElementById("staffList");
  const tenderList = document.getElementById("tenderList");

  try {
    const response = await fetch("./scripts/live-data.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    liveDataCache = data;

    // ===== 首页统计卡片：用 stats 填充并重新动画 =====
    const stats = data.stats || {};
    const provCount = (stats.province_enterprise || [])
      .filter(p => p.province_code !== "000000" && p.count > 0).length;
    const updateCounter = (id, value) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.setAttribute("data-counter", String(value));
      el.textContent = "0";
      animateCounter(el);
    };
    updateCounter("idx-provinces", provCount);
    updateCounter("idx-enterprise", stats.total_enterprise || 0);
    updateCounter("idx-staff", stats.total_staff || 0);
    updateCounter("idx-tender", stats.total_tender || 0);

    if (liveMeta) {
      liveMeta.textContent = `最新批次：${data.run_id || "-"}，更新时间：${data.updated_at || "-"}`;
    }

    const render = (container, list, formatter) => {
      if (!container) return;
      if (!Array.isArray(list) || list.length === 0) {
        container.innerHTML = '<p class="hint">暂无数据</p>';
        return;
      }
      container.innerHTML = list
        .map((row) => formatter(row))
        .join("");
    };

    render(
      enterpriseList,
      data.enterprise || [],
      (row) => `
      <div class="live-item">
        <h4><a class="link" href="./pages/enterprise.html?id=${encodeURIComponent(String(row.id || ""))}">${row.name || "-"}</a></h4>
        <p>统一社会信用代码：${row.uscc || "-"}</p>
        <p>地区：${row.city_name || "-"}｜状态：${row.status || "-"}</p>
      </div>`
    );

    render(
      staffList,
      data.staff || [],
      (row) => `
      <div class="live-item">
        <h4><a class="link" href="./pages/person.html?id=${encodeURIComponent(String(row.id || ""))}">${row.name || "-"}</a></h4>
        <p>人员编码：${row.project_code || "-"}</p>
        <p>地区：${row.city_name || "-"}｜状态：${row.status || "-"}</p>
      </div>`
    );

    render(
      tenderList,
      data.tender || [],
      (row) => `
      <div class="live-item">
        <h4><a class="link" href="./pages/project.html?id=${encodeURIComponent(String(row.id || ""))}">${row.name || "-"}</a></h4>
        <p>项目编号：${row.project_code || "-"}</p>
        <p>地区：${row.city_name || "-"}｜日期：${row.event_date || "-"}</p>
      </div>`
    );
  } catch (err) {
    if (liveMeta) {
      liveMeta.textContent = `数据加载失败：${String(err)}`;
    }
  }
}

loadLiveData().then(() => {
  // 加载完数据后填充省份下拉
  const provSelect = document.getElementById("provinceFilter");
  if (provSelect && liveDataCache.stats && Array.isArray(liveDataCache.stats.province_enterprise)) {
    const provs = liveDataCache.stats.province_enterprise.filter(
      (p) => p.province_code !== "000000" && p.count > 0,
    );
    provSelect.innerHTML = '<option value="">全部省份</option>' +
      provs.map((p) => `<option value="${p.province_name}">${p.province_name} (${p.count.toLocaleString()})</option>`).join("");
  }
  const hintCount = document.getElementById("searchHintCount");
  if (hintCount && liveDataCache.stats) {
    hintCount.textContent = (liveDataCache.stats.total_enterprise || 0).toLocaleString();
  }
});

/* ===== Enterprise Search (Live Data) ===== */
const searchForm = document.getElementById("searchForm");
const searchResults = document.getElementById("searchResults");

if (searchForm && searchResults) {
  // 异步搜索：先试 /api/enterprise?q=，回退到 liveDataCache 客户端过滤
  const renderResults = (items, totalCount) => {
    if (!items || items.length === 0) {
      searchResults.innerHTML =
        '<p style="color:var(--text-soft);padding:8px 0">未找到匹配的企业，请调整搜索关键词或筛选条件</p>';
      return;
    }
    const shown = items.slice(0, 50);
    const remaining = (totalCount != null ? totalCount : items.length) - shown.length;
    const more = remaining > 0
      ? `<p style="color:var(--text-soft);padding:8px 0;text-align:center">… 另外 ${remaining.toLocaleString()} 条未显示，请缩小搜索范围</p>`
      : "";
    const total = totalCount != null ? totalCount : items.length;
    searchResults.innerHTML =
      `<p style="color:var(--text-soft);padding:8px 0;font-size:0.92em">共 <b>${total.toLocaleString()}</b> 条匹配</p>` +
      shown
        .map(
          (ent) => `
          <div class="search-result-item" onclick="window.location.href='pages/enterprise.html?id=${encodeURIComponent(String(ent.id || ""))}'">
            <div class="search-result-info">
              <h4>${ent.name}</h4>
              <p>${ent.uscc || "-"}</p>
            </div>
            <div class="search-result-score">
              <b>${ent.status || "-"}</b>
              <span>${ent.city_name || "-"}</span>
            </div>
          </div>`,
        )
        .join("") + more;
  };

  const doSearch = async () => {
    const keyword = document.getElementById("keyword").value.trim();
    const provFilter = (document.getElementById("provinceFilter") || {}).value || "";

    // 优先走 /api/enterprise
    try {
      const params = new URLSearchParams({ size: "50" });
      if (keyword) params.set("q", keyword);
      if (provFilter) params.set("province", provFilter);
      const resp = await fetch("/api/enterprise?" + params.toString(), { cache: "no-store" });
      if (resp.ok) {
        const payload = await resp.json();
        if (payload && payload.ok) {
          renderResults(payload.items || [], payload.total);
          return;
        }
      }
    } catch (_e) {
      // fallback 到客户端
    }

    // Fallback: 全量客户端过滤（live-data.json 已在 loadLiveData 缓存）
    const base = liveDataCache.enterprise || [];
    const filtered = base.filter((ent) => {
      const provOk = !provFilter || (ent.city_name || "").includes(provFilter);
      if (!provOk) return false;
      if (!keyword) return true;
      const kw = keyword.toUpperCase();
      return (
        (ent.name || "").includes(keyword) ||
        (ent.uscc || "").toUpperCase().includes(kw)
      );
    });
    renderResults(filtered, filtered.length);
  };

  searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    doSearch();
  });
  const provSelect = document.getElementById("provinceFilter");
  if (provSelect) provSelect.addEventListener("change", doSearch);

  const keywordInput = document.getElementById("keyword");
  let searchTimer = null;
  keywordInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(doSearch, 250);
  });
}

/* ===== Nav Active Style ===== */
const style = document.createElement("style");
style.textContent = `
  .nav a.active { color: var(--accent-light) !important; }
  .nav a { transition: color 0.2s, background 0.2s; }
`;
document.head.appendChild(style);

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

loadLiveData();

/* ===== Enterprise Search (Live Data) ===== */
const searchForm = document.getElementById("searchForm");
const searchResults = document.getElementById("searchResults");

if (searchForm && searchResults) {
  searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const keyword = document.getElementById("keyword").value.trim();
    if (!keyword) {
      searchResults.innerHTML = '<p style="color:var(--text-soft);padding:8px 0">请输入企业名称或信用代码进行搜索</p>';
      return;
    }

    const results = (liveDataCache.enterprise || []).filter(
      (ent) => (ent.name || "").includes(keyword) || (ent.uscc || "").includes(keyword.toUpperCase())
    );

    if (results.length === 0) {
      searchResults.innerHTML = '<p style="color:var(--text-soft);padding:8px 0">未找到匹配的企业，请调整搜索关键词</p>';
      return;
    }

    searchResults.innerHTML = results
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
        </div>
      `
      )
      .join("");
  });

  // Real-time search hint
  const keywordInput = document.getElementById("keyword");
  keywordInput.addEventListener("input", () => {
    if (keywordInput.value.trim().length > 0) {
      const results = (liveDataCache.enterprise || []).filter(
        (ent) =>
          (ent.name || "").includes(keywordInput.value.trim()) ||
          (ent.uscc || "").includes(keywordInput.value.trim().toUpperCase())
      );
      if (results.length > 0 && results.length <= 5) {
        searchResults.innerHTML = results
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
            </div>
          `
          )
          .join("");
      } else {
        searchResults.innerHTML = "";
      }
    } else {
      searchResults.innerHTML = "";
    }
  });
}

/* ===== Nav Active Style ===== */
const style = document.createElement("style");
style.textContent = `
  .nav a.active { color: var(--accent-light) !important; }
  .nav a { transition: color 0.2s, background 0.2s; }
`;
document.head.appendChild(style);

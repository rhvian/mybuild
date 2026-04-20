/* ===== Dashboard Logic — live data from live-data.json ===== */

(async function initDashboard() {
  const formatNumber = (n) => (typeof n === "number" ? n.toLocaleString("zh-CN") : "0");
  const setText = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };

  // Load data
  let data = null;
  try {
    const resp = await fetch("../scripts/live-data.json", { cache: "no-store" });
    if (resp.ok) data = await resp.json();
  } catch (e) {
    console.warn("live-data.json load failed", e);
  }
  if (!data) {
    setText("stat-enterprise", "—");
    setText("stat-staff", "—");
    setText("stat-tender", "—");
    setText("stat-provinces", "—");
    return;
  }

  const stats = data.stats || {};

  // Top stats
  setText("stat-enterprise", formatNumber(stats.total_enterprise || 0));
  setText("stat-staff", formatNumber(stats.total_staff || 0));
  setText("stat-tender", formatNumber(stats.total_tender || 0));
  const provinceCount = (stats.province_enterprise || []).filter(p => p.province_code !== "000000" && p.count > 0).length;
  setText("stat-provinces", provinceCount);

  // Update timestamp
  const updated = data.updated_at;
  const today = document.getElementById("today");
  if (today && updated) today.textContent = updated.slice(0, 19).replace("T", " ");

  // Province chart (Top 15)
  const provinceChart = document.getElementById("provinceChart");
  if (provinceChart) {
    const rows = (stats.province_enterprise || [])
      .filter(p => p.province_code !== "000000")
      .slice(0, 15);
    const max = Math.max(...rows.map(r => r.count), 1);
    provinceChart.innerHTML = rows.map(p => {
      const pct = ((p.count / max) * 100).toFixed(1);
      return `<div class="chart-bar-row"><span class="chart-label">${p.province_name}</span><div class="chart-bar" style="--w:${pct}%"><em>${p.count.toLocaleString()}</em></div></div>`;
    }).join("");
  }

  // Staff register type chart
  const staffChart = document.getElementById("staffTypeChart");
  if (staffChart) {
    const types = (stats.staff_register_type || []).slice(0, 10);
    if (types.length === 0) {
      staffChart.innerHTML = `<div class="chart-bar-row"><span class="chart-label">暂无人员注册类别数据</span><div class="chart-bar" style="--w:0%"></div></div>`;
    } else {
      const max = Math.max(...types.map(t => t.count), 1);
      const colors = ["", "bar-accent", "bar-warn", "bar-info", "bar-danger"];
      staffChart.innerHTML = types.map((t, i) => {
        const pct = ((t.count / max) * 100).toFixed(1);
        const cls = colors[i % colors.length];
        return `<div class="chart-bar-row"><span class="chart-label">${t.register_type}</span><div class="chart-bar ${cls}" style="--w:${pct}%"><em>${t.count.toLocaleString()}</em></div></div>`;
      }).join("");
    }
  }

  // Type grid
  const typeGrid = document.getElementById("typeGrid");
  if (typeGrid) {
    const entries = Object.entries(stats.total_by_type || {})
      .sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((s, e) => s + e[1], 0) || 1;
    const labelMap = {
      enterprise: "建筑企业",
      staff: "从业人员",
      tender: "项目/招标",
      portal_entry: "省级入口",
      entry_probe_link: "入口探测链接",
      entry_probe: "入口探测页",
      portal_index: "省平台首页",
      policy_notice: "政策通报",
      endpoint_catalog: "接口目录",
    };
    typeGrid.innerHTML = entries.map(([k, v]) => {
      const pct = ((v / total) * 100).toFixed(1);
      const label = labelMap[k] || k;
      return `<div class="grade-item"><b>${label}</b><span>${v.toLocaleString()}</span><div class="grade-bar" style="--w:${pct}%"></div></div>`;
    }).join("");
  }

  // Recent runs table
  const runsBody = document.getElementById("runsBody");
  if (runsBody) {
    const runs = stats.recent_runs || [];
    if (runs.length === 0) {
      runsBody.innerHTML = `<tr><td colspan="6">暂无数据</td></tr>`;
    } else {
      runsBody.innerHTML = runs.map(r => {
        const start = (r.started_at || "").slice(0, 19).replace("T", " ");
        const end = (r.ended_at || "").slice(0, 19).replace("T", " ") || "-";
        const issueBadge = r.issue_count > 0
          ? `<span class="status warn">${r.issue_count}</span>`
          : `<span class="status ok">0</span>`;
        return `<tr>
          <td><code>${r.run_id.slice(0, 16)}</code></td>
          <td>${start}</td>
          <td>${end}</td>
          <td>${(r.raw_count || 0).toLocaleString()}</td>
          <td>${(r.normalized_count || 0).toLocaleString()}</td>
          <td>${issueBadge}</td>
        </tr>`;
      }).join("");
    }
  }

  // Trend chart — use recent_runs
  drawTrendChart(stats.recent_runs || []);
})();


function drawTrendChart(runs) {
  const canvas = document.getElementById("trendCanvas");
  if (!canvas || runs.length === 0) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;

  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 200 * dpr;
  canvas.style.width = rect.width + "px";
  canvas.style.height = "200px";
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = 200;
  const padding = { top: 20, right: 20, bottom: 40, left: 50 };

  // Oldest first for left-to-right timeline
  const series = runs.slice().reverse();
  const values = series.map(r => r.normalized_count || 0);
  const labels = series.map(r => {
    const t = r.started_at || "";
    return t.slice(5, 10).replace("-", "/"); // MM/DD
  });
  const maxVal = Math.max(...values, 1) * 1.15;

  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Grid
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }

  // Y labels
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.font = "11px sans-serif";
  ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i;
    const val = Math.round(maxVal - (maxVal / 4) * i);
    ctx.fillText(val.toLocaleString(), padding.left - 6, y + 4);
  }

  // X labels
  ctx.textAlign = "center";
  const stepX = values.length > 1 ? chartW / (values.length - 1) : 0;
  labels.forEach((m, i) => {
    if (values.length <= 8 || i % Math.ceil(values.length / 8) === 0) {
      const x = padding.left + stepX * i;
      ctx.fillText(m, x, height - 12);
    }
  });

  if (values.length < 2) {
    // Single point — show as a big dot
    ctx.beginPath();
    ctx.arc(width / 2, height / 2, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#2b7de9";
    ctx.fill();
    return;
  }

  const points = values.map((v, i) => ({
    x: padding.left + stepX * i,
    y: padding.top + chartH * (1 - v / maxVal),
  }));

  // Gradient fill
  const grad = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  grad.addColorStop(0, "rgba(43, 125, 233, 0.35)");
  grad.addColorStop(1, "rgba(43, 125, 233, 0.02)");

  ctx.beginPath();
  ctx.moveTo(points[0].x, height - padding.bottom);
  points.forEach((p) => ctx.lineTo(p.x, p.y));
  ctx.lineTo(points[points.length - 1].x, height - padding.bottom);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const cpx = (prev.x + curr.x) / 2;
    ctx.bezierCurveTo(cpx, prev.y, cpx, curr.y, curr.x, curr.y);
  }
  ctx.strokeStyle = "#2b7de9";
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // Dots
  points.forEach((p) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#2b7de9";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
    ctx.fillStyle = "#0a1628";
    ctx.fill();
  });
}

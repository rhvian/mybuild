/* ===== Dashboard Page Logic ===== */

// Draw trend chart on canvas
const canvas = document.getElementById("trendCanvas");
if (canvas) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;

  // Set canvas size
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 200 * dpr;
  canvas.style.width = rect.width + "px";
  canvas.style.height = "200px";
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = 200;
  const padding = { top: 20, right: 20, bottom: 30, left: 40 };

  // Mock data: monthly warning counts
  const months = ["10月", "11月", "12月", "1月", "2月", "3月", "4月"];
  const values = [11200, 10500, 9800, 10200, 9500, 10100, 9842];
  const maxVal = Math.max(...values) * 1.1;

  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Draw grid lines
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }

  // Draw Y axis labels
  ctx.fillStyle = "rgba(255,255,255,0.4)";
  ctx.font = "11px sans-serif";
  ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i;
    const val = Math.round(maxVal - (maxVal / 4) * i);
    ctx.fillText(val.toLocaleString(), padding.left - 6, y + 4);
  }

  // Draw X axis labels
  ctx.textAlign = "center";
  const stepX = chartW / (months.length - 1);
  months.forEach((m, i) => {
    const x = padding.left + stepX * i;
    ctx.fillText(m, x, height - 8);
  });

  // Draw line
  const points = values.map((v, i) => ({
    x: padding.left + stepX * i,
    y: padding.top + chartH * (1 - v / maxVal),
  }));

  // Gradient fill
  const grad = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  grad.addColorStop(0, "rgba(43, 125, 233, 0.25)");
  grad.addColorStop(1, "rgba(43, 125, 233, 0.02)");

  ctx.beginPath();
  ctx.moveTo(points[0].x, height - padding.bottom);
  points.forEach((p) => ctx.lineTo(p.x, p.y));
  ctx.lineTo(points[points.length - 1].x, height - padding.bottom);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Line stroke
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

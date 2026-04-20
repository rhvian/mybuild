/* ===== Admin 采集控制台 前端 =====
 *
 * 依赖：auth-guard.js 已设置 localStorage['cm_auth']（含 token）
 * 后端：collector.control_server 暴露 /api/collect/* 和 /api/health
 *
 * 没在控制台 section 时自动停止轮询，避免空跑。
 */

(function () {
  const POLL_INTERVAL_MS = 2500;
  const LOG_LINES = 80;

  const $ = (id) => document.getElementById(id);

  function getToken() {
    try {
      const raw = localStorage.getItem("cm_auth");
      if (!raw) return null;
      const p = JSON.parse(raw);
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
      resp = await fetch(path, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      return { ok: false, networkError: true, error: String(e) };
    }
    let data = null;
    try {
      data = await resp.json();
    } catch (e) {
      data = null;
    }
    if (!resp.ok) {
      return { ok: false, status: resp.status, data, error: (data && data.error) || resp.statusText };
    }
    return { ok: true, status: resp.status, data };
  }

  // ===== 状态渲染 =====

  function formatElapsed(sec) {
    if (sec == null || sec < 0) return "—";
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    const parts = [];
    if (h) parts.push(h + "h");
    if (h || m) parts.push(m + "m");
    parts.push(s + "s");
    return parts.join(" ");
  }

  function setDotState(state) {
    const dot = $("cc-dot");
    const label = $("cc-state-label");
    if (!dot || !label) return;
    dot.classList.remove("dot-running", "dot-idle", "dot-error");
    if (state === "running") {
      dot.classList.add("dot-running");
      label.textContent = "运行中";
    } else if (state === "error") {
      dot.classList.add("dot-error");
      label.textContent = "异常";
    } else {
      dot.classList.add("dot-idle");
      label.textContent = "空闲";
    }
  }

  function renderStatus(data) {
    if (!data) return;
    const proc = data.process || {};
    setDotState(proc.running ? "running" : "idle");
    $("cc-pid").textContent = proc.pid || "—";
    $("cc-elapsed").textContent = proc.running ? formatElapsed(proc.elapsed_sec) : "—";

    const lr = data.latest_run;
    if (lr) {
      const short = (lr.run_id || "").slice(0, 16);
      const issueTag = lr.issue_count > 0 ? `（issues=${lr.issue_count}）` : "";
      $("cc-run").textContent = `${short} · raw=${lr.raw_count} norm=${lr.normalized_count}${issueTag}`;
    } else {
      $("cc-run").textContent = "—";
    }

    const cumul = data.cumulative || [];
    const biz = cumul.filter((x) => ["enterprise", "staff", "tender"].includes(x.entity_type));
    $("cc-norm").textContent = biz.length
      ? biz.map((x) => `${x.entity_type}=${x.count.toLocaleString()}`).join("  ")
      : (cumul[0] ? `${cumul[0].entity_type}=${cumul[0].count.toLocaleString()}` : "—");

    // 日志
    const tail = data.log_tail || [];
    renderLog(tail);
    $("cc-log-file").textContent = data.log_file ? "log: " + data.log_file.replace(/^.*\//, "") : "";

    // 最近 runs 表
    renderRuns(data.recent_runs || []);
  }

  function renderLog(lines) {
    const pre = $("cc-log");
    if (!pre) return;
    if (!lines.length) {
      pre.textContent = "（尚无日志）";
      return;
    }
    pre.textContent = lines.join("\n");
    if ($("cc-follow") && $("cc-follow").checked) {
      pre.scrollTop = pre.scrollHeight;
    }
  }

  function renderRuns(runs) {
    const body = $("cc-runs-body");
    if (!body) return;
    if (!runs.length) {
      body.innerHTML = `<tr><td colspan="7" class="muted">暂无运行记录</td></tr>`;
      return;
    }
    body.innerHTML = runs
      .map((r) => {
        const s = (r.started_at || "").slice(0, 19).replace("T", " ");
        const e = (r.ended_at || "").slice(0, 19).replace("T", " ") || "—";
        const issueBadge = r.issue_count > 0
          ? `<span class="status warn">${r.issue_count}</span>`
          : `<span class="status ok">0</span>`;
        const failedBadge = r.failed_source_count > 0
          ? `<span class="status warn">${r.failed_source_count}</span>`
          : `<span class="status ok">0</span>`;
        return `<tr>
          <td><code>${(r.run_id || "").slice(0, 16)}</code></td>
          <td>${s}</td>
          <td>${e}</td>
          <td>${(r.raw_count || 0).toLocaleString()}</td>
          <td>${(r.normalized_count || 0).toLocaleString()}</td>
          <td>${issueBadge}</td>
          <td>${failedBadge}</td>
        </tr>`;
      })
      .join("");
  }

  function renderHealth(res) {
    const badge = $("cc-health-badge");
    const list = $("cc-health-list");
    if (!badge || !list) return;
    if (!res.ok) {
      badge.className = "badge-health badge-health-critical";
      badge.textContent = "不可用";
      list.innerHTML = `<li class="muted">控制服务未响应：${res.error || "unknown"}</li>`;
      return;
    }
    const data = res.data || {};
    const status = data.status || "UNKNOWN";
    const cls = status === "OK" ? "badge-health-ok" : status === "WARN" ? "badge-health-warn" : "badge-health-critical";
    badge.className = "badge-health " + cls;
    badge.textContent = status;
    const detail = data.detail || [];
    if (!detail.length) {
      list.innerHTML = `<li class="muted">一切正常。</li>`;
    } else {
      list.innerHTML = detail
        .map((line) => {
          const parts = line.split("\t");
          const lvl = parts[0] || "INFO";
          const msg = parts.slice(1).join("\t") || line;
          const lvlCls = ({ CRITICAL: "hl-critical", WARN: "hl-warn", OK: "hl-ok", INFO: "hl-info" })[lvl] || "hl-info";
          return `<li><span class="hl ${lvlCls}">${lvl}</span> ${msg}</li>`;
        })
        .join("");
    }
  }

  // ===== 动作 =====

  function flash(msg, type) {
    const el = $("cc-feedback");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("flash-ok", "flash-err", "flash-info");
    if (type === "ok") el.classList.add("flash-ok");
    else if (type === "err") el.classList.add("flash-err");
    else el.classList.add("flash-info");
  }

  async function refreshStatus() {
    const res = await api("GET", "/api/collect/status");
    if (!res.ok) {
      setDotState("error");
      if (res.networkError) flash("控制服务未启动或不可达。请先 `python3 -m collector.control_server`", "err");
      else if (res.status === 401) flash("未授权，请重新登录", "err");
      return;
    }
    renderStatus(res.data);
  }

  async function refreshHealth() {
    renderHealth({ ok: true, data: { status: "…", detail: [] } });
    const res = await api("GET", "/api/health");
    renderHealth(res);
  }

  async function startCollect(only) {
    flash(`正在启动 ${only}…`, "info");
    const res = await api("POST", "/api/collect/start", { only });
    if (res.ok) {
      flash(`已启动（${only}） pid=${res.data.pid || "-"}`, "ok");
    } else if (res.status === 409) {
      flash("已有采集任务在跑，请先停止或等待当前运行结束", "err");
    } else {
      flash(`启动失败：${res.error || res.status}`, "err");
    }
    setTimeout(refreshStatus, 400);
  }

  async function stopCollect() {
    if (!confirm("确认停止当前采集？已落库的数据不会丢。")) return;
    flash("正在安全停止…", "info");
    const res = await api("POST", "/api/collect/stop");
    if (res.ok) {
      flash("已停止", "ok");
    } else {
      flash(`停止失败：${res.error || res.status}`, "err");
    }
    setTimeout(refreshStatus, 400);
  }

  // ===== 轮询生命周期 =====

  let pollTimer = null;
  function startPolling() {
    refreshStatus();
    if (pollTimer) return;
    pollTimer = setInterval(refreshStatus, POLL_INTERVAL_MS);
  }
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // ===== 初始化 =====

  document.addEventListener("DOMContentLoaded", () => {
    // 按钮
    document.querySelectorAll("[data-cc-start]").forEach((btn) => {
      btn.addEventListener("click", () => startCollect(btn.dataset.ccStart));
    });
    const stopBtn = $("cc-stop");
    if (stopBtn) stopBtn.addEventListener("click", stopCollect);
    const refreshBtn = $("cc-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", refreshStatus);
    const healthBtn = $("cc-health-refresh");
    if (healthBtn) healthBtn.addEventListener("click", refreshHealth);

    // 监听侧栏切换：进入 collect 开始轮询，离开停止
    document.querySelectorAll(".sidebar-link[data-section]").forEach((link) => {
      link.addEventListener("click", () => {
        if (link.dataset.section === "collect") {
          startPolling();
          refreshHealth();
        } else {
          stopPolling();
        }
      });
    });

    // 如果默认就在 collect 区，也立即开始
    const currentActive = document.querySelector(".sidebar-link.active");
    if (currentActive && currentActive.dataset.section === "collect") {
      startPolling();
      refreshHealth();
    }
  });

  // 离开页面时停止轮询
  window.addEventListener("beforeunload", stopPolling);
})();

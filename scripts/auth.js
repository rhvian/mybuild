/* ===== Auth Page Logic (v0.4 — JWT via backend /auth/login) =====
 *
 * 登录：POST /auth/login {email, password} → { access_token, refresh_token, expires_in }
 * 存储：localStorage['cm_auth'] = { user, token, refresh_token, expires_at }
 *   - token 既用于 backend（/auth /users /alerts 等），也兼容 control_server（/api/collect /api/health）
 *     因为 control_server 已支持 HS256 JWT 验证（与 backend 共用 jwt_secret.key）
 *
 * 默认凭据（生产环境必改）：admin@example.com / build2026
 * 修改方式：在服务器上编辑 /etc/mybuild/backend.env
 *   MYBUILD_BOOTSTRAP_ADMIN_EMAIL=...
 *   MYBUILD_BOOTSTRAP_ADMIN_PASSWORD=...
 * 然后通过 admin 后台 -> 用户管理 改密 / 加用户。
 */

const authTabs = document.querySelectorAll(".auth-tab");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const authMsg = document.getElementById("authMsg");

authTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    authTabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");

    const target = tab.dataset.tab;
    if (target === "login") {
      loginForm.classList.remove("hidden");
      registerForm.classList.add("hidden");
    } else {
      loginForm.classList.add("hidden");
      registerForm.classList.remove("hidden");
    }
    if (authMsg) {
      authMsg.textContent = "";
      authMsg.className = "auth-msg";
    }
  });
});

document.querySelectorAll(".toggle-pass").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = btn.previousElementSibling;
    input.type = input.type === "password" ? "text" : "password";
  });
});

function writeSession(user, access, refresh, expiresIn) {
  const payload = {
    user,
    token: access,
    refresh_token: refresh,
    issued_at: Date.now(),
    expires_at: Date.now() + expiresIn * 1000,
  };
  try {
    localStorage.setItem("cm_auth", JSON.stringify(payload));
  } catch (e) {
    console.warn("localStorage write failed", e);
  }
}

function backTarget() {
  const params = new URLSearchParams(location.search);
  const back = params.get("back");
  if (back && back.startsWith("/") && !back.startsWith("//")) return back;
  return "admin.html";
}

if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const emailOrUser = document.getElementById("loginUser").value.trim();
    const pass = document.getElementById("loginPass").value;

    if (!emailOrUser || !pass) {
      showMsg("请填写账号和密码", "error");
      return;
    }

    try {
      const resp = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: emailOrUser, password: pass }),
      });
      if (resp.status === 429) {
        const body = await resp.json().catch(() => ({}));
        const wait = body?.detail?.retry_after_sec ?? 900;
        showMsg(`登录尝试过于频繁，请 ${Math.ceil(wait / 60)} 分钟后再试`, "error");
        return;
      }
      if (resp.status === 401 || resp.status === 403) {
        showMsg("账号或密码错误", "error");
        return;
      }
      if (!resp.ok) {
        showMsg(`登录失败：HTTP ${resp.status}`, "error");
        return;
      }
      const data = await resp.json();
      writeSession(emailOrUser, data.access_token, data.refresh_token, data.expires_in);
      showMsg("登录成功，正在跳转...", "success");
      setTimeout(() => {
        window.location.href = backTarget();
      }, 500);
    } catch (err) {
      showMsg(`网络异常：${String(err)}（请确认 backend 已启动）`, "error");
    }
  });
}

if (registerForm) {
  registerForm.addEventListener("submit", (e) => {
    e.preventDefault();
    showMsg("v0.4 暂未开放自助注册。请联系管理员在 admin 后台 → 用户管理 中添加账号。", "info");
  });
}

function showMsg(text, type) {
  if (!authMsg) return;
  authMsg.textContent = text;
  authMsg.className = "auth-msg " + type;
}

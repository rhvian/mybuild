/* ===== Auth Page Logic =====
 *
 * L1 级最简认证（前端口令校验）：
 *   - 允许凭据的 SHA-256(`username:password`) 写在下方 ALLOWED_CREDS 白名单里
 *   - 默认口令：admin / build2026
 *   - 修改方式：在项目根运行
 *       python3 -c "import hashlib; print(hashlib.sha256(b'你的用户:你的口令').hexdigest())"
 *     把输出 hash 替换 ALLOWED_CREDS 数组里的条目即可
 *
 * 限制（已知）：
 *   - 前端可见的哈希不防拆包；只做"不让无关人随便进"
 *   - L2 阶段随 FastAPI + JWT 后端替换，本文件会废弃
 */

const ALLOWED_CREDS = [
  // admin / build2026
  "56cae9c8e0450378092d0e86824f175e91c11acc79cfc4d4f986e5cb4719192f",
];
const SESSION_MAX_AGE_MS = 8 * 60 * 60 * 1000; // 8h

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

async function sha256Hex(text) {
  const buf = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function writeSession(user, token) {
  const payload = {
    user,
    token,
    issued_at: Date.now(),
    expires_at: Date.now() + SESSION_MAX_AGE_MS,
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

async function verifyWithServer(user, pass) {
  // 尝试调 control_server /api/auth/verify；服务不可用则回退
  try {
    const resp = await fetch("/api/auth/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user, password: pass }),
    });
    const data = await resp.json();
    if (resp.status === 200 && data && data.ok && data.token) {
      return { source: "server", ok: true, token: data.token };
    }
    if (resp.status === 401) {
      return { source: "server", ok: false, error: "invalid_credentials" };
    }
    return { source: "server", ok: false, error: "server_error_" + resp.status };
  } catch (e) {
    return { source: "offline", ok: null };
  }
}

if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const user = document.getElementById("loginUser").value.trim();
    const pass = document.getElementById("loginPass").value;

    if (!user || !pass) {
      showMsg("请填写用户名和密码", "error");
      return;
    }

    const clientHash = await sha256Hex(`${user}:${pass}`);
    const srv = await verifyWithServer(user, pass);

    if (srv.source === "server") {
      if (!srv.ok) {
        showMsg("用户名或密码错误", "error");
        return;
      }
      writeSession(user, srv.token);
      showMsg("登录成功，正在跳转...", "success");
    } else {
      // 控制服务不可达，回退到纯前端校验
      if (!ALLOWED_CREDS.includes(clientHash)) {
        showMsg("用户名或密码错误", "error");
        return;
      }
      writeSession(user, clientHash);
      showMsg("登录成功（控制服务未运行，部分功能将不可用）", "info");
    }

    setTimeout(() => {
      window.location.href = backTarget();
    }, 700);
  });
}

if (registerForm) {
  registerForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const name = document.getElementById("regName").value.trim();
    const code = document.getElementById("regCode").value.trim();
    const phone = document.getElementById("regPhone").value.trim();
    const pass = document.getElementById("regPass").value;
    const pass2 = document.getElementById("regPass2").value;

    if (!name || !code || !phone || !pass || !pass2) {
      showMsg("请填写所有必填项", "error");
      return;
    }
    if (code.length !== 18) {
      showMsg("统一社会信用代码应为18位", "error");
      return;
    }
    if (!/^1\d{10}$/.test(phone)) {
      showMsg("请输入正确的手机号", "error");
      return;
    }
    if (pass.length < 8 || !/[a-zA-Z]/.test(pass) || !/\d/.test(pass)) {
      showMsg("密码需8-20位，包含字母和数字", "error");
      return;
    }
    if (pass !== pass2) {
      showMsg("两次输入的密码不一致", "error");
      return;
    }

    showMsg("v0.3 暂未开放注册，请使用平台预设账号登录（默认 admin / build2026）", "info");
  });
}

function showMsg(text, type) {
  if (!authMsg) return;
  authMsg.textContent = text;
  authMsg.className = "auth-msg " + type;
}

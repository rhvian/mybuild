/* ===== Auth Page Logic ===== */
const authTabs = document.querySelectorAll(".auth-tab");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const authMsg = document.getElementById("authMsg");

// Tab switching
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

// Password toggle
document.querySelectorAll(".toggle-pass").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = btn.previousElementSibling;
    if (input.type === "password") {
      input.type = "text";
    } else {
      input.type = "password";
    }
  });
});

// Login form
if (loginForm) {
  loginForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const user = document.getElementById("loginUser").value.trim();
    const pass = document.getElementById("loginPass").value;

    if (!user || !pass) {
      showMsg("请填写用户名和密码", "error");
      return;
    }

    if (pass.length < 6) {
      showMsg("密码长度不能少于6位", "error");
      return;
    }

    // Mock login
    showMsg("登录成功，正在跳转...", "success");
    setTimeout(() => {
      window.location.href = "admin.html";
    }, 1200);
  });
}

// Register form
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

    showMsg("注册申请已提交，等待审核", "success");
  });
}

function showMsg(text, type) {
  if (!authMsg) return;
  authMsg.textContent = text;
  authMsg.className = "auth-msg " + type;
}

/* ===== Admin Page Logic ===== */

const sidebarLinks = document.querySelectorAll(".sidebar-link[data-section]");
const adminSections = document.querySelectorAll(".admin-section");
const adminTitle = document.getElementById("adminTitle");

const sectionTitles = {
  overview: "工作台",
  enterprises: "企业管理",
  warnings: "预警处置",
  penalties: "惩戒管理",
  projects: "项目监管",
  users: "用户管理",
};

sidebarLinks.forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    sidebarLinks.forEach((l) => l.classList.remove("active"));
    link.classList.add("active");

    const section = link.dataset.section;
    adminSections.forEach((sec) => {
      const secId = sec.id.replace("sec", "").toLowerCase();
      sec.classList.toggle("hidden", secId !== section);
    });

    if (adminTitle && sectionTitles[section]) {
      adminTitle.textContent = sectionTitles[section];
    }
  });
});

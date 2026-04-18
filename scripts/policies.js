/* ===== Policies Page Logic ===== */

// Category filter
const filterBtns = document.querySelectorAll(".filter-btn");
const policyItems = document.querySelectorAll(".policy-full-list .policy-item");

filterBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    filterBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    const filter = btn.dataset.filter;
    policyItems.forEach((item) => {
      if (filter === "all" || item.dataset.category === filter) {
        item.style.display = "";
      } else {
        item.style.display = "none";
      }
    });
  });
});

// Search
const policySearch = document.getElementById("policySearch");
if (policySearch) {
  policySearch.addEventListener("submit", (e) => {
    e.preventDefault();
    const keyword = document.getElementById("policyKeyword").value.trim().toLowerCase();
    if (!keyword) {
      policyItems.forEach((item) => (item.style.display = ""));
      return;
    }

    policyItems.forEach((item) => {
      const text = item.textContent.toLowerCase();
      item.style.display = text.includes(keyword) ? "" : "none";
    });

    // Reset filter buttons
    filterBtns.forEach((b) => b.classList.remove("active"));
    filterBtns[0].classList.add("active");
  });
}

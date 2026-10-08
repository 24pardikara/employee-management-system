/* Employee Management System - frontend logic (vanilla JS, no page reloads) */

const API_BASE =
  location.port === "5000" || location.protocol === "file:"
    ? "http://127.0.0.1:5000/api"
    : `${location.origin}/api`;

const form = document.getElementById("employee-form");
const formTitle = document.getElementById("form-title");
const submitBtn = document.getElementById("submit-btn");
const cancelBtn = document.getElementById("cancel-btn");
const tbody = document.getElementById("employee-body");
const statusMsg = document.getElementById("status-msg");
const searchInput = document.getElementById("search-input");
const searchField = document.getElementById("search-field");
const statusFilter = document.getElementById("status-filter");
const deptFilter = document.getElementById("dept-filter");
const clearBtn = document.getElementById("clear-filters");
const exportBtn = document.getElementById("export-btn");
const deptList = document.getElementById("dept-list");

const fields = ["emp_id", "name", "email", "department", "designation",
                "salary", "contact", "status", "date_joined"];
let editingId = null;
let sortKey = "id";
let sortOrder = "desc";

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
function setStatus(msg, type = "") {
  statusMsg.textContent = msg;
  statusMsg.className = "status" + (type ? " " + type : "");
}

function fmtMoney(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function validateForm(data) {
  const errors = [];
  if (editingId === null) {
    if (!data.emp_id) errors.push("Employee ID is required.");
    else if (!/^[A-Za-z0-9_-]{2,20}$/.test(data.emp_id))
      errors.push("Employee ID must be 2-20 chars (letters, digits, - or _).");
  }
  if (!data.name) errors.push("Name is required.");
  if (!data.email) errors.push("Email is required.");
  else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email)) errors.push("Email must be a valid address.");
  if (!data.department) errors.push("Department is required.");
  if (!data.designation) errors.push("Designation is required.");
  if (data.salary === "") errors.push("Salary is required.");
  else if (Number.isNaN(Number(data.salary))) errors.push("Salary must be a valid number.");
  else if (Number(data.salary) < 0) errors.push("Salary cannot be negative.");
  if (!data.contact) errors.push("Contact is required.");
  else if (!/^[0-9+\-\s()]{7,20}$/.test(data.contact))
    errors.push("Contact must be 7-20 chars (digits, spaces, + - ( ) allowed).");
  return errors;
}

function buildQuery() {
  const params = new URLSearchParams();
  const q = searchInput.value.trim();
  if (q) { params.set("q", q); params.set("field", searchField.value); }
  if (statusFilter.value) params.set("status", statusFilter.value);
  if (deptFilter.value) params.set("department", deptFilter.value);
  params.set("sort", sortKey);
  params.set("order", sortOrder);
  return params;
}

// --------------------------------------------------------------------------- //
// Rendering
// --------------------------------------------------------------------------- //
function renderRows(employees) {
  tbody.innerHTML = "";
  if (!employees.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="9">No employees found.</td></tr>`;
    return;
  }
  for (const e of employees) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(e.emp_id)}</td>
      <td>
        <div>${escapeHtml(e.name)}</div>
        <small style="color:var(--muted)">${escapeHtml(e.email)}</small>
      </td>
      <td>${escapeHtml(e.department)}</td>
      <td>${escapeHtml(e.designation)}</td>
      <td class="num">${fmtMoney(e.salary)}</td>
      <td>${escapeHtml(e.contact)}</td>
      <td><span class="pill" data-status="${escapeHtml(e.status)}">${escapeHtml(e.status)}</span></td>
      <td>${escapeHtml(e.date_joined)}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-sm btn-edit" data-action="edit" data-id="${escapeHtml(e.emp_id)}">Edit</button>
        <button class="btn btn-sm btn-delete" data-action="delete" data-id="${escapeHtml(e.emp_id)}">Delete</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

function renderSortArrows() {
  document.querySelectorAll("th[data-sort] .arrow").forEach((el) => (el.textContent = ""));
  const th = document.querySelector(`th[data-sort="${sortKey}"] .arrow`);
  if (th) th.textContent = sortOrder === "asc" ? "▲" : "▼";
}

function renderStats(s) {
  document.getElementById("stat-total").textContent = s.total;
  document.getElementById("stat-active").textContent = s.active;
  document.getElementById("stat-depts").textContent = s.departments;
  document.getElementById("stat-payroll").textContent = fmtMoney(s.total_payroll);
  document.getElementById("stat-avg").textContent = fmtMoney(s.avg_salary);

  const max = Math.max(1, ...s.by_department.map((d) => d.count));
  const bd = document.getElementById("breakdown");
  bd.innerHTML = s.by_department.map((d) => `
    <div class="bd-row">
      <span class="bd-name">${escapeHtml(d.department)}</span>
      <span class="bd-track"><span class="bd-fill" style="width:${(d.count / max) * 100}%"></span></span>
      <span class="bd-count">${d.count}</span>
    </div>`).join("");
}

function renderDeptOptions(depts) {
  const current = deptFilter.value;
  deptFilter.innerHTML = `<option value="">All departments</option>` +
    depts.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join("");
  deptFilter.value = current;
  deptList.innerHTML = depts.map((d) => `<option value="${escapeHtml(d)}"></option>`).join("");
}

// --------------------------------------------------------------------------- //
// Data loading
// --------------------------------------------------------------------------- //
async function loadEmployees() {
  try {
    const res = await fetch(`${API_BASE}/employees?${buildQuery()}`);
    const data = await res.json();
    renderRows(data);
    renderSortArrows();
    const filtered = searchInput.value || statusFilter.value || deptFilter.value;
    setStatus(`${data.length} ${filtered ? "result" : "employee"}(s).`);
  } catch {
    setStatus("Could not reach the server. Is the Flask backend running?", "error");
  }
}

async function loadStats() {
  try {
    const res = await fetch(`${API_BASE}/stats`);
    renderStats(await res.json());
  } catch { /* stats are non-critical */ }
}

async function loadDepartments() {
  try {
    const res = await fetch(`${API_BASE}/departments`);
    renderDeptOptions(await res.json());
  } catch { /* ignore */ }
}

function refreshAll() {
  loadEmployees();
  loadStats();
  loadDepartments();
}

// --------------------------------------------------------------------------- //
// Form handling
// --------------------------------------------------------------------------- //
function readForm() {
  const data = {};
  fields.forEach((f) => (data[f] = document.getElementById(f).value.trim()));
  return data;
}

function resetForm() {
  form.reset();
  editingId = null;
  formTitle.textContent = "Add Employee";
  submitBtn.textContent = "Add Employee";
  cancelBtn.classList.add("hidden");
  document.getElementById("emp_id").disabled = false;
}

function enterEditMode(emp) {
  editingId = emp.emp_id;
  fields.forEach((f) => (document.getElementById(f).value = emp[f]));
  document.getElementById("emp_id").disabled = true;
  formTitle.textContent = `Edit Employee: ${emp.emp_id}`;
  submitBtn.textContent = "Save changes";
  cancelBtn.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = readForm();
  if (editingId !== null) data.emp_id = editingId;

  const errors = validateForm(data);
  if (errors.length) return setStatus(errors.join(" "), "error");

  try {
    const url = editingId === null
      ? `${API_BASE}/employees`
      : `${API_BASE}/employees/${encodeURIComponent(editingId)}`;
    const method = editingId === null ? "POST" : "PUT";
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const body = await res.json();
    if (!res.ok) return setStatus(body.error || "Request failed.", "error");
    setStatus(editingId === null
      ? `Added ${body.name} (${body.emp_id}).`
      : `Updated ${body.emp_id}.`, "success");
    resetForm();
    refreshAll();
  } catch {
    setStatus("Request failed. Check the server.", "error");
  }
});

cancelBtn.addEventListener("click", resetForm);

// Row actions
tbody.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const empId = btn.dataset.id;

  if (btn.dataset.action === "edit") {
    try {
      const res = await fetch(`${API_BASE}/employees/${encodeURIComponent(empId)}`);
      const body = await res.json();
      if (!res.ok) return setStatus(body.error || "Could not load employee.", "error");
      enterEditMode(body);
    } catch { setStatus("Request failed.", "error"); }
  } else if (btn.dataset.action === "delete") {
    if (!confirm(`Delete employee ${empId}? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_BASE}/employees/${encodeURIComponent(empId)}`, { method: "DELETE" });
      const body = await res.json();
      if (!res.ok) return setStatus(body.error || "Delete failed.", "error");
      setStatus(body.message, "success");
      if (editingId === empId) resetForm();
      refreshAll();
    } catch { setStatus("Request failed.", "error"); }
  }
});

// Sorting
document.querySelectorAll("th[data-sort]").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (sortKey === key) sortOrder = sortOrder === "asc" ? "desc" : "asc";
    else { sortKey = key; sortOrder = "asc"; }
    loadEmployees();
  });
});

// Search + filters (debounced search)
let searchTimer;
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadEmployees, 250);
});
searchField.addEventListener("change", loadEmployees);
statusFilter.addEventListener("change", loadEmployees);
deptFilter.addEventListener("change", loadEmployees);
clearBtn.addEventListener("click", () => {
  searchInput.value = "";
  searchField.value = "all";
  statusFilter.value = "";
  deptFilter.value = "";
  loadEmployees();
});

// Export respects current filters
exportBtn.addEventListener("click", () => {
  window.location = `${API_BASE}/employees/export?${buildQuery()}`;
});

// Initial load
refreshAll();

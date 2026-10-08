"""
Pytest unit/integration tests for the Employee Management System API.

Each test runs against a fresh, isolated SQLite database in a temp dir, so the
suite never touches the real employees.db. Run from the backend/ folder:

    pip install -r requirements.txt
    pytest -v
"""

import os
import sqlite3
import sys

import pytest

# Make the backend package importable when pytest is run from any cwd.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    """A test client backed by a throwaway seeded database."""
    db_path = os.path.join(tmp_path, "test.db")
    app = create_app(db_path=db_path, seed=True)
    app.init_db()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def empty_app(tmp_path):
    """An unseeded app + its db path, so tests can inspect the raw schema."""
    db_path = os.path.join(tmp_path, "empty.db")
    app = create_app(db_path=db_path, seed=False)
    app.init_db()
    app.config["TESTING"] = True
    return app, db_path


@pytest.fixture
def empty_client(empty_app):
    """A test client with an empty (unseeded) database."""
    app, _ = empty_app
    with app.test_client() as c:
        yield c


VALID = {
    "emp_id": "E9001",
    "name": "Test Person",
    "email": "test.person@acme.com",
    "department": "Engineering",
    "designation": "Developer",
    "salary": "750000",
    "contact": "9876543210",
    "status": "Active",
    "date_joined": "2024-05-01",
}


# --------------------------------------------------------------------------- #
# List / seed
# --------------------------------------------------------------------------- #
def test_seeded_list(client):
    res = client.get("/api/employees")
    assert res.status_code == 200
    assert len(res.get_json()) == 6


def test_empty_list(empty_client):
    res = empty_client.get("/api/employees")
    assert res.status_code == 200
    assert res.get_json() == []


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def test_add_employee(empty_client):
    res = empty_client.post("/api/employees", json=VALID)
    assert res.status_code == 201
    body = res.get_json()
    assert body["emp_id"] == "E9001"
    assert body["id"] == 1
    assert empty_client.get("/api/employees").get_json()[0]["name"] == "Test Person"


def test_duplicate_emp_id(empty_client):
    empty_client.post("/api/employees", json=VALID)
    res = empty_client.post("/api/employees", json=VALID)
    assert res.status_code == 409
    assert "already exists" in res.get_json()["error"]


def test_add_defaults_date_and_status(empty_client):
    payload = {k: v for k, v in VALID.items() if k not in ("date_joined", "status")}
    res = empty_client.post("/api/employees", json=payload)
    assert res.status_code == 201
    body = res.get_json()
    assert body["status"] == "Active"
    assert body["date_joined"]  # auto-filled with today's date


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field,value,msg", [
    ("salary", "abc", "valid number"),
    ("salary", "-5", "negative"),
    ("email", "not-an-email", "valid address"),
    ("contact", "12", "7-20 chars"),
    ("emp_id", "!", "2-20 chars"),
    ("status", "Vacationing", "Status must be"),
    ("date_joined", "01-01-2024", "YYYY-MM-DD"),
])
def test_validation_rejects_bad_input(empty_client, field, value, msg):
    payload = dict(VALID)
    payload[field] = value
    res = empty_client.post("/api/employees", json=payload)
    assert res.status_code == 400
    assert msg in res.get_json()["error"]


def test_missing_required_fields(empty_client):
    res = empty_client.post("/api/employees", json={})
    assert res.status_code == 400
    assert len(res.get_json()["errors"]) >= 5


# --------------------------------------------------------------------------- #
# Read one
# --------------------------------------------------------------------------- #
def test_get_one(client):
    res = client.get("/api/employees/E1001")
    assert res.status_code == 200
    assert res.get_json()["name"] == "Asha Rao"


def test_get_missing(client):
    res = client.get("/api/employees/NOPE")
    assert res.status_code == 404


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #
def test_update_employee(client):
    res = client.put("/api/employees/E1001", json={
        "name": "Asha Rao", "email": "asha@acme.com", "department": "Engineering",
        "designation": "Principal Engineer", "salary": "1500000",
        "contact": "9876500001", "status": "Active", "date_joined": "2021-03-15",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["designation"] == "Principal Engineer"
    assert body["salary"] == 1500000


def test_update_missing(client):
    res = client.put("/api/employees/NOPE", json=VALID)
    assert res.status_code == 404


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #
def test_delete_employee(client):
    res = client.delete("/api/employees/E1001")
    assert res.status_code == 200
    assert client.get("/api/employees/E1001").status_code == 404


def test_delete_missing(client):
    res = client.delete("/api/employees/NOPE")
    assert res.status_code == 404


# --------------------------------------------------------------------------- #
# Search / filter / sort
# --------------------------------------------------------------------------- #
def test_search_by_department(client):
    res = client.get("/api/employees?q=Engineering&field=department")
    data = res.get_json()
    assert len(data) == 2
    assert all(e["department"] == "Engineering" for e in data)


def test_search_by_name(client):
    res = client.get("/api/employees?q=Asha&field=name")
    assert len(res.get_json()) == 1


def test_filter_by_status(client):
    res = client.get("/api/employees?status=On Leave")
    data = res.get_json()
    assert len(data) == 1
    assert data[0]["name"] == "Meera Nair"


def test_sort_by_salary_asc(client):
    res = client.get("/api/employees?sort=salary&order=asc")
    salaries = [e["salary"] for e in res.get_json()]
    assert salaries == sorted(salaries)


def test_sort_injection_is_ignored(client):
    # A bogus/unsafe sort column must fall back to the default, not error.
    res = client.get("/api/employees?sort=salary;DROP TABLE employees")
    assert res.status_code == 200
    assert len(res.get_json()) == 6


# --------------------------------------------------------------------------- #
# Departments / stats / export
# --------------------------------------------------------------------------- #
def test_departments(client):
    res = client.get("/api/departments")
    depts = res.get_json()
    assert "Engineering" in depts
    assert depts == sorted(depts)


def test_stats(client):
    res = client.get("/api/stats")
    body = res.get_json()
    assert body["total"] == 6
    assert body["active"] == 4
    assert body["departments"] == 5
    assert body["total_payroll"] > 0
    assert any(d["department"] == "Engineering" and d["count"] == 2
               for d in body["by_department"])


def test_export_csv(client):
    res = client.get("/api/employees/export")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    text = res.get_data(as_text=True)
    assert "emp_id,name,email" in text.splitlines()[0]
    # header + 6 rows
    assert len([ln for ln in text.splitlines() if ln.strip()]) == 7


# --------------------------------------------------------------------------- #
# Normalization (schema structure)
# --------------------------------------------------------------------------- #
def test_schema_has_lookup_tables(empty_app):
    _, db_path = empty_app
    conn = sqlite3.connect(db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"departments", "designations", "employees"} <= names


def test_employees_reference_lookups_by_fk(empty_app):
    _, db_path = empty_app
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(employees)")}
    fks = {(r[2], r[3]) for r in conn.execute("PRAGMA foreign_key_list(employees)")}
    conn.close()
    # employees store foreign keys, not free-text department/designation
    assert "department_id" in cols and "designation_id" in cols
    assert "department" not in cols and "designation" not in cols
    assert ("departments", "department_id") in fks
    assert ("designations", "designation_id") in fks


def test_department_not_duplicated(empty_client, empty_app):
    _, db_path = empty_app
    # Two employees in the same department must share one departments row.
    a = dict(VALID, emp_id="E1", department="Engineering")
    b = dict(VALID, emp_id="E2", email="b@acme.com", department="Engineering")
    empty_client.post("/api/employees", json=a)
    empty_client.post("/api/employees", json=b)
    conn = sqlite3.connect(db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM departments WHERE name='Engineering'").fetchone()[0]
    conn.close()
    assert n == 1

"""
Employee Management System - Flask backend (REST API + static frontend server).

A full employee management app built on an app factory so it is easy to test.

API (all JSON unless noted):
    GET    /api/employees            List/search/filter/sort employees
    GET    /api/employees/<emp_id>   Fetch a single employee
    POST   /api/employees            Add a new employee
    PUT    /api/employees/<emp_id>   Update an existing employee
    DELETE /api/employees/<emp_id>   Delete an employee
    GET    /api/employees/export     Download all (filtered) employees as CSV
    GET    /api/departments          Distinct department list
    GET    /api/stats                Dashboard metrics (counts, payroll, breakdown)

Run:  python app.py   ->  http://127.0.0.1:5000
"""

import csv
import io
import os
import re
import sqlite3
from datetime import date

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "employees.db")
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

STATUSES = ("Active", "On Leave", "Inactive")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONTACT_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")
EMP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Columns the client is allowed to sort by -> safe (qualified) SQL column names.
SORTABLE = {
    "emp_id": "e.emp_id",
    "name": "e.name",
    "department": "d.name",
    "designation": "g.title",
    "salary": "e.salary",
    "status": "e.status",
    "date_joined": "e.date_joined",
}

# Base SELECT that joins the normalized lookup tables and exposes department /
# designation under the same names the flat API used, so responses are unchanged.
EMP_SELECT = """
    SELECT e.id, e.emp_id, e.name, e.email,
           d.name  AS department,
           g.title AS designation,
           e.salary, e.contact, e.status, e.date_joined
    FROM employees e
    JOIN departments  d ON e.department_id  = d.id
    JOIN designations g ON e.designation_id = g.id
"""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_payload(data, require_emp_id=True):
    """Return (clean_dict, errors_list). Shared by POST and PUT."""
    errors = []
    clean = {}

    emp_id = str(data.get("emp_id", "")).strip()
    if require_emp_id:
        if not emp_id:
            errors.append("Employee ID is required.")
        elif not EMP_ID_RE.match(emp_id):
            errors.append("Employee ID must be 2-20 chars (letters, digits, - or _).")
    clean["emp_id"] = emp_id

    name = str(data.get("name", "")).strip()
    if not name:
        errors.append("Name is required.")
    clean["name"] = name

    email = str(data.get("email", "")).strip()
    if not email:
        errors.append("Email is required.")
    elif not EMAIL_RE.match(email):
        errors.append("Email must be a valid address.")
    clean["email"] = email

    department = str(data.get("department", "")).strip()
    if not department:
        errors.append("Department is required.")
    clean["department"] = department

    designation = str(data.get("designation", "")).strip()
    if not designation:
        errors.append("Designation is required.")
    clean["designation"] = designation

    salary_raw = str(data.get("salary", "")).strip()
    if not salary_raw:
        errors.append("Salary is required.")
    else:
        try:
            salary = float(salary_raw)
            if salary < 0:
                errors.append("Salary cannot be negative.")
            else:
                clean["salary"] = salary
        except ValueError:
            errors.append("Salary must be a valid number.")

    contact = str(data.get("contact", "")).strip()
    if not contact:
        errors.append("Contact is required.")
    elif not CONTACT_RE.match(contact):
        errors.append("Contact must be 7-20 chars (digits, spaces, + - ( ) allowed).")
    clean["contact"] = contact

    status = str(data.get("status", "Active")).strip() or "Active"
    if status not in STATUSES:
        errors.append(f"Status must be one of: {', '.join(STATUSES)}.")
    clean["status"] = status

    date_joined = str(data.get("date_joined", "")).strip()
    if not date_joined:
        date_joined = date.today().isoformat()
    elif not DATE_RE.match(date_joined):
        errors.append("Date joined must be in YYYY-MM-DD format.")
    clean["date_joined"] = date_joined

    return clean, errors


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(db_path=None, seed=True):
    app = Flask(__name__, static_folder=None)
    CORS(app)
    app.config["DB_PATH"] = db_path or DEFAULT_DB_PATH

    def get_db():
        conn = sqlite3.connect(app.config["DB_PATH"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def get_or_create(conn, table, col, value):
        """Return the id of the lookup row for `value`, creating it if needed.

        `table` and `col` are fixed internal constants (never user input), so the
        f-string interpolation here is safe from injection.
        """
        row = conn.execute(f"SELECT id FROM {table} WHERE {col} = ?", (value,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(f"INSERT INTO {table} ({col}) VALUES (?)", (value,))
        return cur.lastrowid

    # expose helper on the app so route closures can use it
    app.get_or_create = get_or_create

    def init_db():
        conn = get_db()
        # Normalized schema: lookup tables + employees referencing them by FK.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS departments (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS designations (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS employees (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_id         TEXT    NOT NULL UNIQUE,
                name           TEXT    NOT NULL,
                email          TEXT    NOT NULL,
                department_id  INTEGER NOT NULL REFERENCES departments(id),
                designation_id INTEGER NOT NULL REFERENCES designations(id),
                salary         REAL    NOT NULL,
                contact        TEXT    NOT NULL,
                status         TEXT    NOT NULL DEFAULT 'Active',
                date_joined    TEXT    NOT NULL
            );
            """
        )
        conn.commit()

        if seed:
            count = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
            if count == 0:
                rows = [
                    ("E1001", "Asha Rao", "asha.rao@acme.com", "Engineering",
                     "Senior Developer", 1250000, "9876500001", "Active", "2021-03-15"),
                    ("E1002", "Vikram Shah", "vikram.shah@acme.com", "Sales",
                     "Account Manager", 850000, "9876500002", "Active", "2022-07-01"),
                    ("E1003", "Meera Nair", "meera.nair@acme.com", "Human Resources",
                     "HR Lead", 920000, "9876500003", "On Leave", "2020-11-20"),
                    ("E1004", "Rohan Gupta", "rohan.gupta@acme.com", "Engineering",
                     "QA Engineer", 700000, "9876500004", "Active", "2023-01-10"),
                    ("E1005", "Priya Menon", "priya.menon@acme.com", "Finance",
                     "Financial Analyst", 780000, "9876500005", "Active", "2022-02-28"),
                    ("E1006", "Arjun Das", "arjun.das@acme.com", "Marketing",
                     "Content Strategist", 660000, "9876500006", "Inactive", "2019-09-05"),
                ]
                for (emp_id, name, email, dept, desig, salary, contact, status, joined) in rows:
                    dept_id = get_or_create(conn, "departments", "name", dept)
                    desig_id = get_or_create(conn, "designations", "title", desig)
                    conn.execute(
                        """INSERT INTO employees
                           (emp_id, name, email, department_id, designation_id,
                            salary, contact, status, date_joined)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (emp_id, name, email, dept_id, desig_id, salary, contact, status, joined),
                    )
                conn.commit()
        conn.close()

    def query_employees(conn):
        """Build a filtered/sorted query from request args and run it."""
        q = request.args.get("q", "").strip()
        field = request.args.get("field", "all").strip().lower()
        status = request.args.get("status", "").strip()
        dept = request.args.get("department", "").strip()
        sort = request.args.get("sort", "id").strip().lower()
        order = request.args.get("order", "desc").strip().lower()

        where, params = [], []
        if q:
            like = f"%{q}%"
            if field == "id":
                where.append("e.emp_id LIKE ?"); params.append(like)
            elif field == "name":
                where.append("e.name LIKE ?"); params.append(like)
            elif field == "department":
                where.append("d.name LIKE ?"); params.append(like)
            else:
                where.append("(e.emp_id LIKE ? OR e.name LIKE ? OR d.name LIKE ? OR e.email LIKE ?)")
                params += [like, like, like, like]
        if status in STATUSES:
            where.append("e.status = ?"); params.append(status)
        if dept:
            where.append("d.name = ?"); params.append(dept)

        sql = EMP_SELECT
        if where:
            sql += " WHERE " + " AND ".join(where)

        sort_col = SORTABLE.get(sort, "e.id")
        direction = "ASC" if order == "asc" else "DESC"
        sql += f" ORDER BY {sort_col} {direction}"

        return conn.execute(sql, params).fetchall()

    # ----------------------------------------------------------------------- #
    # API routes
    # ----------------------------------------------------------------------- #
    @app.route("/api/employees", methods=["GET"])
    def list_employees():
        conn = get_db()
        rows = query_employees(conn)
        conn.close()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/employees/export", methods=["GET"])
    def export_employees():
        conn = get_db()
        rows = query_employees(conn)
        conn.close()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["emp_id", "name", "email", "department", "designation",
                         "salary", "contact", "status", "date_joined"])
        for r in rows:
            writer.writerow([r["emp_id"], r["name"], r["email"], r["department"],
                             r["designation"], r["salary"], r["contact"],
                             r["status"], r["date_joined"]])
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=employees.csv"},
        )

    @app.route("/api/departments", methods=["GET"])
    def departments():
        conn = get_db()
        rows = conn.execute("SELECT name FROM departments ORDER BY name").fetchall()
        conn.close()
        return jsonify([r["name"] for r in rows])

    @app.route("/api/stats", methods=["GET"])
    def stats():
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM employees WHERE status = 'Active'"
        ).fetchone()["n"]
        dept_count = conn.execute(
            "SELECT COUNT(DISTINCT department_id) AS n FROM employees"
        ).fetchone()["n"]
        agg = conn.execute(
            "SELECT COALESCE(SUM(salary),0) AS total, COALESCE(AVG(salary),0) AS avg FROM employees"
        ).fetchone()
        by_dept = conn.execute(
            """SELECT d.name AS department, COUNT(*) AS count,
                      COALESCE(SUM(e.salary),0) AS payroll
               FROM employees e JOIN departments d ON e.department_id = d.id
               GROUP BY d.name ORDER BY count DESC"""
        ).fetchall()
        conn.close()
        return jsonify({
            "total": total,
            "active": active,
            "departments": dept_count,
            "total_payroll": round(agg["total"], 2),
            "avg_salary": round(agg["avg"], 2),
            "by_department": [dict(r) for r in by_dept],
        })

    @app.route("/api/employees/<emp_id>", methods=["GET"])
    def get_employee(emp_id):
        conn = get_db()
        row = conn.execute(EMP_SELECT + " WHERE e.emp_id = ?", (emp_id,)).fetchone()
        conn.close()
        if row is None:
            return jsonify({"error": f"No employee with ID '{emp_id}'."}), 404
        return jsonify(dict(row))

    @app.route("/api/employees", methods=["POST"])
    def add_employee():
        data = request.get_json(silent=True) or {}
        clean, errors = validate_payload(data, require_emp_id=True)
        if errors:
            return jsonify({"error": " ".join(errors), "errors": errors}), 400

        conn = get_db()
        if conn.execute("SELECT 1 FROM employees WHERE emp_id = ?", (clean["emp_id"],)).fetchone():
            conn.close()
            return jsonify({"error": f"Employee ID '{clean['emp_id']}' already exists."}), 409

        dept_id = get_or_create(conn, "departments", "name", clean["department"])
        desig_id = get_or_create(conn, "designations", "title", clean["designation"])
        cur = conn.execute(
            """INSERT INTO employees
               (emp_id, name, email, department_id, designation_id,
                salary, contact, status, date_joined)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (clean["emp_id"], clean["name"], clean["email"], dept_id, desig_id,
             clean["salary"], clean["contact"], clean["status"], clean["date_joined"]),
        )
        conn.commit()
        row = conn.execute(EMP_SELECT + " WHERE e.id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        return jsonify(dict(row)), 201

    @app.route("/api/employees/<emp_id>", methods=["PUT"])
    def update_employee(emp_id):
        data = request.get_json(silent=True) or {}
        data["emp_id"] = emp_id  # key comes from the URL, not editable
        clean, errors = validate_payload(data, require_emp_id=False)
        if errors:
            return jsonify({"error": " ".join(errors), "errors": errors}), 400

        conn = get_db()
        if not conn.execute("SELECT 1 FROM employees WHERE emp_id = ?", (emp_id,)).fetchone():
            conn.close()
            return jsonify({"error": f"No employee with ID '{emp_id}'."}), 404

        dept_id = get_or_create(conn, "departments", "name", clean["department"])
        desig_id = get_or_create(conn, "designations", "title", clean["designation"])
        conn.execute(
            """UPDATE employees
               SET name = ?, email = ?, department_id = ?, designation_id = ?,
                   salary = ?, contact = ?, status = ?, date_joined = ?
               WHERE emp_id = ?""",
            (clean["name"], clean["email"], dept_id, desig_id,
             clean["salary"], clean["contact"], clean["status"],
             clean["date_joined"], emp_id),
        )
        conn.commit()
        row = conn.execute(EMP_SELECT + " WHERE e.emp_id = ?", (emp_id,)).fetchone()
        conn.close()
        return jsonify(dict(row))

    @app.route("/api/employees/<emp_id>", methods=["DELETE"])
    def delete_employee(emp_id):
        conn = get_db()
        cur = conn.execute("DELETE FROM employees WHERE emp_id = ?", (emp_id,))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if deleted == 0:
            return jsonify({"error": f"No employee with ID '{emp_id}' to delete."}), 404
        return jsonify({"message": f"Employee '{emp_id}' deleted."})

    # ----------------------------------------------------------------------- #
    # Frontend
    # ----------------------------------------------------------------------- #
    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/<path:path>")
    def static_proxy(path):
        return send_from_directory(FRONTEND_DIR, path)

    app.init_db = init_db  # expose for tests / __main__
    return app


if __name__ == "__main__":
    app = create_app()
    app.init_db()
    print("Employee Management System running at http://127.0.0.1:5000")
    app.run(debug=True, port=5000)

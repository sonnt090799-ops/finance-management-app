from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, url_for

from .db import Money, connect, init_db, month_key, rows_to_dicts, to_int

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY="dev",  # for local dev; replace in production
        DATABASE_PATH=str(Path(app.instance_path) / "finance.sqlite3"),
    )

    @app.before_request
    def _open_db() -> None:
        db_path = Path(app.config["DATABASE_PATH"])
        conn = connect(db_path)
        init_db(conn)
        g.db = conn

    @app.teardown_request
    def _close_db(_exc: Exception | None) -> None:
        conn: sqlite3.Connection | None = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.get("/")
    def dashboard():
        today = date.today()
        month = request.args.get("month") or month_key(today)
        start = f"{month}-01"
        # end: next month first day (SQLite date math)
        end = datetime.strptime(start, "%Y-%m-%d").date().replace(day=28)
        # We'll rely on LIKE month% for simplicity in queries.

        txs = g.db.execute(
            """
            SELECT t.*, c.name AS category_name, c.kind AS category_kind
            FROM tx t
            LEFT JOIN category c ON c.id = t.category_id
            WHERE t.tx_date LIKE ? || '%'
            ORDER BY t.tx_date DESC, t.id DESC
            LIMIT 8
            """,
            (month,),
        ).fetchall()

        income = (
            g.db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) AS v FROM tx WHERE tx_date LIKE ?||'%' AND amount_cents > 0",
                (month,),
            ).fetchone()["v"]
            or 0
        )
        expense = (
            g.db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) AS v FROM tx WHERE tx_date LIKE ?||'%' AND amount_cents < 0",
                (month,),
            ).fetchone()["v"]
            or 0
        )
        net = income + expense

        by_cat = g.db.execute(
            """
            SELECT COALESCE(c.name, 'Uncategorized') AS name,
                   COALESCE(c.kind, CASE WHEN t.amount_cents >= 0 THEN 'income' ELSE 'expense' END) AS kind,
                   SUM(t.amount_cents) AS total_cents
            FROM tx t
            LEFT JOIN category c ON c.id = t.category_id
            WHERE t.tx_date LIKE ? || '%'
            GROUP BY 1,2
            ORDER BY ABS(total_cents) DESC
            """,
            (month,),
        ).fetchall()

        # budgets (expenses only)
        budgets = g.db.execute(
            """
            SELECT b.amount_cents AS budget_cents,
                   c.name AS category_name,
                   COALESCE(SUM(t.amount_cents), 0) AS actual_cents
            FROM budget b
            JOIN category c ON c.id = b.category_id
            LEFT JOIN tx t
              ON t.category_id = b.category_id
             AND t.tx_date LIKE b.month || '%'
            WHERE b.month = ?
            GROUP BY b.id
            ORDER BY c.name ASC
            """,
            (month,),
        ).fetchall()

        return render_template(
            "dashboard.html",
            month=month,
            income=Money(int(income)),
            expense=Money(int(expense)),
            net=Money(int(net)),
            recent_txs=rows_to_dicts(txs),
            by_cat=rows_to_dicts(by_cat),
            budgets=rows_to_dicts(budgets),
        )

    @app.get("/transactions")
    def transactions():
        month = request.args.get("month") or month_key(date.today())
        q = (request.args.get("q") or "").strip()
        category_id = to_int(request.args.get("category_id"))

        where = ["t.tx_date LIKE ? || '%'"]
        params: list[object] = [month]

        if q:
            where.append("(t.description LIKE ? OR c.name LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if category_id:
            where.append("t.category_id = ?")
            params.append(category_id)

        txs = g.db.execute(
            f"""
            SELECT t.*, c.name AS category_name, c.kind AS category_kind
            FROM tx t
            LEFT JOIN category c ON c.id = t.category_id
            WHERE {' AND '.join(where)}
            ORDER BY t.tx_date DESC, t.id DESC
            """,
            params,
        ).fetchall()

        categories = g.db.execute(
            "SELECT id, name, kind FROM category ORDER BY kind DESC, name ASC"
        ).fetchall()

        return render_template(
            "transactions.html",
            month=month,
            q=q,
            category_id=category_id,
            categories=rows_to_dicts(categories),
            txs=rows_to_dicts(txs),
        )

    @app.post("/transactions/new")
    def transactions_new():
        tx_date = (request.form.get("tx_date") or "").strip()
        description = (request.form.get("description") or "").strip()
        amount = (request.form.get("amount") or "").strip()
        kind = (request.form.get("kind") or "expense").strip()
        category_id = to_int(request.form.get("category_id"))

        if not tx_date:
            tx_date = date.today().isoformat()
        if not description:
            flash("Description is required.", "danger")
            return redirect(url_for("transactions"))
        try:
            m = Money.from_decimal_str(amount)
        except Exception:
            flash("Amount must be a number like 12.34.", "danger")
            return redirect(url_for("transactions"))

        cents = m.abs().cents
        if kind == "expense":
            cents = -cents

        g.db.execute(
            "INSERT INTO tx (tx_date, description, amount_cents, category_id) VALUES (?,?,?,?)",
            (tx_date, description, int(cents), category_id),
        )
        g.db.commit()
        flash("Transaction added.", "success")
        return redirect(url_for("transactions", month=tx_date[:7]))

    @app.post("/transactions/<int:tx_id>/delete")
    def transactions_delete(tx_id: int):
        row = g.db.execute("SELECT tx_date FROM tx WHERE id = ?", (tx_id,)).fetchone()
        g.db.execute("DELETE FROM tx WHERE id = ?", (tx_id,))
        g.db.commit()
        flash("Transaction deleted.", "success")
        month = (row["tx_date"][:7] if row else month_key(date.today()))
        return redirect(url_for("transactions", month=month))

    @app.get("/categories")
    def categories():
        cats = g.db.execute(
            "SELECT id, name, kind FROM category ORDER BY kind DESC, name ASC"
        ).fetchall()
        return render_template("categories.html", categories=rows_to_dicts(cats))

    @app.post("/categories/new")
    def categories_new():
        name = (request.form.get("name") or "").strip()
        kind = (request.form.get("kind") or "expense").strip()
        if not name:
            flash("Category name is required.", "danger")
            return redirect(url_for("categories"))
        try:
            g.db.execute("INSERT INTO category (name, kind) VALUES (?, ?)", (name, kind))
            g.db.commit()
            flash("Category added.", "success")
        except sqlite3.IntegrityError:
            flash("That category already exists.", "warning")
        return redirect(url_for("categories"))

    @app.post("/categories/<int:category_id>/delete")
    def categories_delete(category_id: int):
        g.db.execute("DELETE FROM category WHERE id = ?", (category_id,))
        g.db.commit()
        flash("Category deleted.", "success")
        return redirect(url_for("categories"))

    @app.get("/budgets")
    def budgets():
        month = request.args.get("month") or month_key(date.today())
        cats = g.db.execute(
            "SELECT id, name, kind FROM category WHERE kind='expense' ORDER BY name ASC"
        ).fetchall()

        rows = g.db.execute(
            """
            SELECT c.id AS category_id,
                   c.name AS category_name,
                   COALESCE(b.amount_cents, 0) AS budget_cents,
                   COALESCE(SUM(t.amount_cents), 0) AS actual_cents
            FROM category c
            LEFT JOIN budget b ON b.category_id = c.id AND b.month = ?
            LEFT JOIN tx t ON t.category_id = c.id AND t.tx_date LIKE ? || '%'
            WHERE c.kind = 'expense'
            GROUP BY c.id
            ORDER BY c.name ASC
            """,
            (month, month),
        ).fetchall()

        return render_template(
            "budgets.html", month=month, categories=rows_to_dicts(cats), rows=rows_to_dicts(rows)
        )

    @app.post("/budgets/set")
    def budgets_set():
        month = (request.form.get("month") or "").strip()
        category_id = to_int(request.form.get("category_id"))
        amount = (request.form.get("amount") or "").strip()
        if not month or not category_id:
            flash("Month and category are required.", "danger")
            return redirect(url_for("budgets"))
        try:
            cents = Money.from_decimal_str(amount).abs().cents
        except Exception:
            flash("Budget amount must be a number like 300.00.", "danger")
            return redirect(url_for("budgets", month=month))

        g.db.execute(
            """
            INSERT INTO budget (month, category_id, amount_cents)
            VALUES (?,?,?)
            ON CONFLICT(month, category_id) DO UPDATE SET amount_cents=excluded.amount_cents
            """,
            (month, category_id, int(cents)),
        )
        g.db.commit()
        flash("Budget saved.", "success")
        return redirect(url_for("budgets", month=month))

    @app.get("/reports")
    def reports():
        month = request.args.get("month") or month_key(date.today())
        # Category breakdown for month
        breakdown = g.db.execute(
            """
            SELECT COALESCE(c.name, 'Uncategorized') AS name,
                   SUM(t.amount_cents) AS total_cents
            FROM tx t
            LEFT JOIN category c ON c.id = t.category_id
            WHERE t.tx_date LIKE ? || '%'
            GROUP BY 1
            ORDER BY ABS(total_cents) DESC
            """,
            (month,),
        ).fetchall()

        # Last 12 months net trend
        trend = g.db.execute(
            """
            WITH months AS (
              SELECT strftime('%Y-%m', date('now', '-' || n || ' months')) AS m
              FROM (
                SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
                UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7
                UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
              )
            )
            SELECT months.m AS month,
                   COALESCE(SUM(t.amount_cents), 0) AS net_cents
            FROM months
            LEFT JOIN tx t ON t.tx_date LIKE months.m || '%'
            GROUP BY months.m
            ORDER BY months.m ASC
            """
        ).fetchall()

        return render_template(
            "reports.html",
            month=month,
            breakdown=rows_to_dicts(breakdown),
            trend=rows_to_dicts(trend),
        )

    return app


app = create_app()


# Financial Management App

A lightweight personal finance app (income/expense tracking, budgets, and reports) built with **Flask + SQLite**.

## Features

- Transactions: add / edit / delete, filter by month, category, and free-text search
- Categories: manage income/expense categories
- Budgets: set monthly budgets per category and see progress
- Dashboard: monthly totals and charts
- Reports: category breakdown + monthly trend

## Run locally

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app finance_management_app.app run --debug
```

Then open `http://127.0.0.1:5000`.

## Data

Data is stored in a local SQLite database at `instance/finance.sqlite3`.


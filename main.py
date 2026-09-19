from fastapi import FastAPI, Request, Form, Depends, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
import secrets
import hashlib
import csv
import io

from fastapi.responses import StreamingResponse

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-only-change-me")
)
templates = Jinja2Templates(directory="templates")

DATABASE_URL = os.environ.get("DATABASE_URL")
RECOVERY_PIN = os.environ.get("RECOVERY_PIN", "2468")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        return None
    return user

import re
from datetime import datetime

def extract_sale_from_text(text: str) -> dict:
    """Guess sale fields from pasted Amazon / notes text. Wife must check."""
    raw = text or ""
    out = {
        "quantity_sold": 1,
        "sale_price": 0.0,
        "amazon_fees": 0.0,
        "sale_date": datetime.now().strftime("%Y-%m-%d"),
        "notes": raw[:500],
        "guess_name": "",
    }

    qty = re.search(r"(?:qty|quantity|units?|sold)\s*[:=]?\s*(\d+)", raw, re.I)
    if qty:
        out["quantity_sold"] = int(qty.group(1))

    # last £ amount often the sale; "fee" / "commission" near a number = fees
    fee = re.search(
        r"(?:fee|fees|commission|fba)[^\d£]{0,20}£?\s*(\d+(?:\.\d{1,2})?)",
        raw,
        re.I,
    )
    if fee:
        out["amazon_fees"] = float(fee.group(1))

    money = re.findall(r"£\s*(\d+(?:\.\d{1,2})?)", raw)
    if not money:
        money = re.findall(r"(\d+\.\d{2})", raw)
    if money:
        amounts = [float(x) for x in money]
        if out["amazon_fees"] and out["amazon_fees"] in amounts:
            amounts = [a for a in amounts if a != out["amazon_fees"]]
        if amounts:
            out["sale_price"] = amounts[0]

    date = re.search(r"(20\d{2}-\d{2}-\d{2})", raw)
    if date:
        out["sale_date"] = date.group(1)

    # first line often the product name
    first = raw.strip().splitlines()[0] if raw.strip() else ""
    out["guess_name"] = first[:80]

    return out

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            product_name TEXT NOT NULL,
            current_stock INTEGER DEFAULT 0,
            cost_price REAL DEFAULT 0,
            units_per_pack INTEGER DEFAULT 1,
            notes TEXT,
            created_at TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            quantity_sold INTEGER,
            sale_price REAL,
            amazon_fees REAL DEFAULT 0,
            net_profit REAL,
            sale_date TEXT,
            notes TEXT,
            created_at TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS amazon_subscriptions (
            id SERIAL PRIMARY KEY,
            charge_date TEXT NOT NULL,
            amount REAL NOT NULL,
            notes TEXT,
            created_at TEXT
        )
    ''')

    cur.execute("SELECT * FROM users LIMIT 1")
    existing_user = cur.fetchone()
    if existing_user is None:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            ("admin", hash_password("everhaven123"))
        )

    conn.commit()
    cur.close()
    conn.close()

init_db()

@app.get("/")
def home(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="home.html"
    )

@app.get("/about")
def about(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={}
    )

@app.get("/backup")
def backup_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="backup.html",
        context={}
    )

def _csv_response(rows, filename):
    output = io.StringIO()
    if rows:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    data = output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/backup/products")
def backup_products(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return _csv_response(rows, "everhaven_products.csv")

@app.get("/backup/sales")
def backup_sales(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sales ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return _csv_response(rows, "everhaven_sales.csv")

@app.get("/backup/subscriptions")
def backup_subscriptions(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM amazon_subscriptions ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return _csv_response(rows, "everhaven_subscriptions.csv")

@app.get("/add-product")
def add_product_form(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="add_product.html"
    )

@app.post("/add-product")
def add_product(
    request: Request,
    product_name: str = Form(...),
    current_stock: int = Form(...),
    cost_price: float = Form(...),
    units_per_pack: int = Form(1),
    notes: str = Form("")
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO products 
           (product_name, current_stock, cost_price, units_per_pack, notes, created_at) 
           VALUES (%s, %s, %s, %s, %s, %s)''',
        (product_name, current_stock, cost_price, units_per_pack, notes, created_at)
    )
    conn.commit()
    cur.close()
    conn.close()

    return RedirectResponse(url="/products", status_code=303)

@app.get("/products")
def view_products(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    cur.close()
    conn.close()
    
    return templates.TemplateResponse(
        request=request,
        name="products.html",
        context={"products": products}
    )

@app.get("/record-sale")
def record_sale_form(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, product_name, current_stock FROM products ORDER BY product_name")
    products = cur.fetchall()
    cur.close()
    conn.close()
    
    return templates.TemplateResponse(
        request=request,
        name="record_sale.html",
        context={"products": products}
    )

@app.post("/record-sale")
def record_sale(
    request: Request,
    product_id: int = Form(...),
    quantity_sold: int = Form(...),
    sale_price: float = Form(...),
    amazon_fees: float = Form(0),
    notes: str = Form("")
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cur.fetchone()
    
    if product is None:
        cur.close()
        conn.close()
        return {"error": "Product not found"}
    
    if quantity_sold > product["current_stock"]:
        cur.close()
        conn.close()
        return {"error": "Not enough stock"}
    
    net_profit = (sale_price * quantity_sold) - (product["cost_price"] * quantity_sold) - amazon_fees
    
    new_stock = product["current_stock"] - quantity_sold
    cur.execute("UPDATE products SET current_stock = %s WHERE id = %s", (new_stock, product_id))
    
    sale_date = datetime.now().strftime("%Y-%m-%d")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cur.execute('''
        INSERT INTO sales (product_id, quantity_sold, sale_price, amazon_fees, net_profit, sale_date, notes, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (product_id, quantity_sold, sale_price, amazon_fees, net_profit, sale_date, notes, created_at))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return RedirectResponse(url="/products", status_code=303)

@app.get("/sales")
def sales_history(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT
            sales.id,
            products.product_name,
            sales.quantity_sold,
            sales.sale_price,
            sales.amazon_fees,
            sales.net_profit,
            sales.sale_date,
            sales.notes
        FROM sales
        JOIN products ON sales.product_id = products.id
        ORDER BY sales.id DESC
    ''')
    sales = cur.fetchall()

    cur.execute("SELECT SUM(net_profit) as total FROM sales")
    total = cur.fetchone()
    sales_profit = total["total"] if total and total["total"] is not None else 0

    cur.execute("SELECT SUM(amount) as total FROM amazon_subscriptions")
    sub = cur.fetchone()
    subscription_total = sub["total"] if sub and sub["total"] is not None else 0

    total_profit = sales_profit - subscription_total

    cur.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="sales.html",
        context={
            "sales": sales,
            "total_profit": total_profit,
            "sales_profit": sales_profit,
            "subscription_total": subscription_total
        }
    )

@app.get("/delete-product/{product_id}")
def delete_product(request: Request, product_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
    conn.commit()
    cur.close()
    conn.close()
    return RedirectResponse(url="/products", status_code=303)

@app.get("/edit-product/{product_id}")
def edit_product_form(request: Request, product_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cur.fetchone()
    cur.close()
    conn.close()

    if product is None:
        return RedirectResponse(url="/products", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="edit_product.html",
        context={"product": product}
    )

@app.post("/edit-product/{product_id}")
def edit_product(
    request: Request,
    product_id: int,
    product_name: str = Form(...),
    current_stock: int = Form(...),
    cost_price: float = Form(...),
    units_per_pack: int = Form(1),
    notes: str = Form("")
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        UPDATE products 
        SET product_name = %s, current_stock = %s, cost_price = %s, units_per_pack = %s, notes = %s
        WHERE id = %s
    ''', (product_name, current_stock, cost_price, units_per_pack, notes, product_id))
    conn.commit()
    cur.close()
    conn.close()

    return RedirectResponse(url="/products", status_code=303)

@app.get("/delete-sale/{sale_id}")
def delete_sale(request: Request, sale_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM sales WHERE id = %s", (sale_id,))
    conn.commit()
    cur.close()
    conn.close()
    return RedirectResponse(url="/sales", status_code=303)

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user and user["password_hash"] == hash_password(password):
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid username or password"}
    )

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

@app.get("/change-password")
def change_password_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="change_password.html"
    )

@app.post("/change-password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if new_password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={"error": "New passwords do not match"}
        )

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (user,))
    db_user = cur.fetchone()

    if db_user["password_hash"] != hash_password(current_password):
        cur.close()
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={"error": "Current password is wrong"}
        )

    cur.execute(
        "UPDATE users SET password_hash = %s WHERE username = %s",
        (hash_password(new_password), user)
    )
    conn.commit()
    cur.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="change_password.html",
        context={"success": "Password changed successfully"}
    )

@app.get("/forgot-password")
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html"
    )

@app.post("/forgot-password")
def forgot_password(
    request: Request,
    recovery_pin: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    if recovery_pin != RECOVERY_PIN:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={"error": "Wrong recovery PIN"}
        )

    if new_password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={"error": "New passwords do not match"}
        )

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash = %s WHERE username = %s",
        (hash_password(new_password), "admin")
    )
    conn.commit()
    cur.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={"success": "Password reset successfully. You can now login."}
    )

@app.get("/amazon-subscription")
def amazon_subscription_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM amazon_subscriptions ORDER BY id DESC")
    charges = cur.fetchall()

    cur.execute("SELECT SUM(amount) as total FROM amazon_subscriptions")
    total = cur.fetchone()
    total_subscription = total["total"] if total and total["total"] is not None else 0

    cur.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="amazon_subscription.html",
        context={
            "charges": charges,
            "total_subscription": total_subscription
        }
    )

@app.get("/paste-sale")
def paste_sale_form(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="paste_sale.html",
        context={"error": None}
    )

@app.post("/paste-sale")
def paste_sale_preview(request: Request, pasted_text: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    guess = extract_sale_from_text(pasted_text)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, product_name, current_stock FROM products ORDER BY product_name")
    products = cur.fetchall()
    cur.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="record_sale.html",
        context={
            "products": products,
            "guess": guess,
        }
    )

@app.post("/amazon-subscription")
def add_amazon_subscription(
    request: Request,
    charge_date: str = Form(...),
    amount: float = Form(...),
    notes: str = Form("")
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO amazon_subscriptions (charge_date, amount, notes, created_at)
           VALUES (%s, %s, %s, %s)''',
        (charge_date, amount, notes, created_at)
    )
    conn.commit()
    cur.close()
    conn.close()

    return RedirectResponse(url="/amazon-subscription", status_code=303)

@app.get("/delete-subscription/{charge_id}")
def delete_subscription(request: Request, charge_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM amazon_subscriptions WHERE id = %s", (charge_id,))
    conn.commit()
    cur.close()
    conn.close()

    return RedirectResponse(url="/amazon-subscription", status_code=303)
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

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="everhaven-secret-key-change-this-later")

templates = Jinja2Templates(directory="templates")

DATABASE_URL = os.environ.get("DATABASE_URL")

# Simple login credentials (we can improve later)
USERNAME = "admin"
PASSWORD = "everhaven123"   # Change this to a strong password later

def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        return None
    return user

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
    total_profit = total["total"] if total and total["total"] is not None else 0

    cur.close()
    conn.close()
    
    return templates.TemplateResponse(
        request=request,
        name="sales.html",
        context={
            "sales": sales,
            "total_profit": total_profit
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
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == USERNAME and password == PASSWORD:
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid username or password"}
    )

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import sqlite3
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")

def get_db_connection():
    conn = sqlite3.connect("amazon.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    # Create products table if not exists
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            current_stock INTEGER DEFAULT 0,
            cost_price REAL DEFAULT 0,
            units_per_pack INTEGER DEFAULT 1,
            notes TEXT,
            created_at TEXT
        )
    ''')

    # Add the new column if it doesn't exist (for existing databases)
    try:
        conn.execute("ALTER TABLE products ADD COLUMN units_per_pack INTEGER DEFAULT 1")
    except:
        pass  # Column already exists

    conn.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            quantity_sold INTEGER,
            sale_price REAL,
            amazon_fees REAL DEFAULT 0,
            net_profit REAL,
            sale_date TEXT,
            notes TEXT,
            created_at TEXT,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html"
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
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    conn.execute(
        '''INSERT INTO products 
           (product_name, current_stock, cost_price, units_per_pack, notes, created_at) 
           VALUES (?, ?, ?, ?, ?, ?)''',
        (product_name, current_stock, cost_price, units_per_pack, notes, created_at)
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/products", status_code=303)

@app.post("/add-product")
def add_product(
    request: Request,
    product_name: str = Form(...),
    current_stock: int = Form(...),
    cost_price: float = Form(...),
    notes: str = Form("")
):
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO products (product_name, current_stock, cost_price, notes, created_at) VALUES (?, ?, ?, ?, ?)",
        (product_name, current_stock, cost_price, notes, created_at)
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/add-product", status_code=303)

@app.get("/products")
def view_products(request: Request):
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    
    return templates.TemplateResponse(
        request=request,
        name="products.html",
        context={"products": products}
    )

@app.get("/record-sale")
def record_sale_form(request: Request):
    conn = get_db_connection()
    products = conn.execute("SELECT id, product_name, current_stock FROM products ORDER BY product_name").fetchall()
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
    conn = get_db_connection()
    
    # Get current product info
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    
    if product is None:
        conn.close()
        return {"error": "Product not found"}
    
    if quantity_sold > product["current_stock"]:
        conn.close()
        return {"error": "Not enough stock"}
    
    # Calculate net profit
    net_profit = (sale_price * quantity_sold) - (product["cost_price"] * quantity_sold) - amazon_fees
    
    # Reduce stock
    new_stock = product["current_stock"] - quantity_sold
    conn.execute("UPDATE products SET current_stock = ? WHERE id = ?", (new_stock, product_id))
    
    # Save the sale
    sale_date = datetime.now().strftime("%Y-%m-%d")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn.execute('''
        INSERT INTO sales (product_id, quantity_sold, sale_price, amazon_fees, net_profit, sale_date, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (product_id, quantity_sold, sale_price, amazon_fees, net_profit, sale_date, notes, created_at))
    
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/products", status_code=303)

@app.get("/sales")
def sales_history(request: Request):
    conn = get_db_connection()
    
    sales = conn.execute('''
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
    ''').fetchall()

    # Calculate total profit
    total_profit = conn.execute("SELECT SUM(net_profit) FROM sales").fetchone()[0]
    if total_profit is None:
        total_profit = 0

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
def delete_product(product_id: int):
    conn = get_db_connection()
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/products", status_code=303)

@app.get("/edit-product/{product_id}")
def edit_product_form(request: Request, product_id: int):
    conn = get_db_connection()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
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
    product_id: int,
    product_name: str = Form(...),
    current_stock: int = Form(...),
    cost_price: float = Form(...),
    units_per_pack: int = Form(1),
    notes: str = Form("")
):
    conn = get_db_connection()
    conn.execute('''
        UPDATE products 
        SET product_name = ?, current_stock = ?, cost_price = ?, units_per_pack = ?, notes = ?
        WHERE id = ?
    ''', (product_name, current_stock, cost_price, units_per_pack, notes, product_id))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/products", status_code=303)
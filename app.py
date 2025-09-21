from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField, BooleanField, IntegerField
from wtforms.validators import DataRequired, NumberRange
from datetime import datetime
import os
import json
import sys
from sqlalchemy import event, text
import urllib.parse

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'

# Enhanced Database Configuration for Azure SQL Database
def get_database_uri():
    """Get appropriate database URI for environment"""
    
    # Method 1: Check for Azure SQL connection string
    if 'SQLAZURECONNSTR_DefaultConnection' in os.environ:
        conn_str = os.environ['SQLAZURECONNSTR_DefaultConnection']
        print("Using Azure SQL Database: alidata.database.windows.net")
        return conn_str
    
    # Method 2: Check for DATABASE_URL
    elif 'DATABASE_URL' in os.environ:
        print("Using DATABASE_URL")
        return os.environ['DATABASE_URL']
    
    # Method 3: Build from individual environment variables
    elif all(key in os.environ for key in ['DB_SERVER', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']):
        server = os.environ['DB_SERVER']
        database = os.environ['DB_NAME']
        username = os.environ['DB_USER']
        password = urllib.parse.quote_plus(os.environ['DB_PASSWORD'])  # URL encode password
        
        # Azure SQL connection string for SQLAlchemy
        conn_str = f"mssql+pyodbc://{username}:{password}@{server}:1433/{database}?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no&Connection+Timeout=30"
        print(f"Built Azure SQL connection for: {server}")
        return conn_str
    
    # Fallback to SQLite for local development
    else:
        if os.environ.get('WEBSITE_SITE_NAME'):  
            # Running on Azure App Service
            db_path = '/tmp/restaurant.db'
            print(f"Azure environment - using SQLite fallback: {db_path}")
        else:
            # Running locally
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'restaurant.db')
            print(f"Local development - using SQLite: {db_path}")
        
        return f'sqlite:///{db_path}'

app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Enhanced engine options for Azure SQL Database
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_recycle': 299,       # Just under Azure's 300-second timeout
    'pool_pre_ping': True,     # Test connections before use
    'pool_timeout': 20,        # Connection timeout
    'max_overflow': 0,         # No overflow connections
    'pool_size': 5,            # Connection pool size
    'echo': False              # Set to True for SQL debugging
}

db = SQLAlchemy(app)

# SQLite pragma settings (only applies to SQLite)
@event.listens_for(db.engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if 'sqlite' in str(dbapi_connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# -------------------- MODELS --------------------
class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    menu_items = db.relationship('MenuItem', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'

class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    image_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<MenuItem {self.name}>'

class Table(db.Model):
    __tablename__ = 'tables'
    
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)
    orders = db.relationship('Order', backref='table', lazy=True)

    def __repr__(self):
        return f'<Table {self.number}>'

class Order(db.Model):
    __tablename__ = 'orders'  # Fixed: Changed from 'order' to 'orders' to avoid SQL reserved keyword
    
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('tables.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')
    total_amount = db.Column(db.Numeric(10, 2), default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.id} - {self.customer_name}>'

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_items.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    menu_item = db.relationship('MenuItem', backref='order_items')

    def get_total_price(self):
        return float(self.quantity * self.price)

    def __repr__(self):
        return f'<OrderItem {self.quantity}x {self.menu_item.name if self.menu_item else "Unknown"}>'

# -------------------- SAMPLE DATA --------------------
def create_sample_data():
    """Create sample data for the restaurant"""
    try:
        print("Creating sample data...")
        
        # Create categories first
        categories_data = [
            {'name': 'Appetizers', 'description': 'Start your meal with these delicious appetizers'},
            {'name': 'Main Course', 'description': 'Our signature main dishes'},
            {'name': 'Desserts', 'description': 'Sweet endings to your meal'},
            {'name': 'Beverages', 'description': 'Refreshing drinks and beverages'}
        ]

        for cat_data in categories_data:
            if not Category.query.filter_by(name=cat_data['name']).first():
                category = Category(**cat_data)
                db.session.add(category)
        
        db.session.commit()
        print("Categories created successfully")

        # Get categories for menu items
        main_course_cat = Category.query.filter_by(name='Main Course').first()
        appetizer_cat = Category.query.filter_by(name='Appetizers').first()
        dessert_cat = Category.query.filter_by(name='Desserts').first()
        beverage_cat = Category.query.filter_by(name='Beverages').first()

        if all([main_course_cat, appetizer_cat, dessert_cat, beverage_cat]):
            menu_items_data = [
                # Main Course
                {
                    'name': 'Chicken Biryani',
                    'description': 'Aromatic basmati rice with tender chicken pieces and traditional spices',
                    'price': 15.99,
                    'category_id': main_course_cat.id,
                    'is_available': True
                },
                {
                    'name': 'Beef Karahi',
                    'description': 'Spicy beef curry cooked in traditional Pakistani style',
                    'price': 18.99,
                    'category_id': main_course_cat.id,
                    'is_available': True
                },
                {
                    'name': 'Lamb Chops',
                    'description': 'Grilled lamb chops marinated with herbs and spices',
                    'price': 22.99,
                    'category_id': main_course_cat.id,
                    'is_available': True
                },
                # Appetizers
                {
                    'name': 'Chicken Tikka',
                    'description': 'Grilled chicken marinated in yogurt and spices',
                    'price': 12.99,
                    'category_id': appetizer_cat.id,
                    'is_available': True
                },
                {
                    'name': 'Samosas (4 pieces)',
                    'description': 'Crispy pastries filled with spiced potatoes and peas',
                    'price': 6.99,
                    'category_id': appetizer_cat.id,
                    'is_available': True
                },
                {
                    'name': 'Seekh Kebab',
                    'description': 'Spiced ground meat grilled on skewers',
                    'price': 10.99,
                    'category_id': appetizer_cat.id,
                    'is_available': True
                },
                # Desserts
                {
                    'name': 'Gulab Jamun',
                    'description': 'Sweet milk dumplings in sugar syrup',
                    'price': 5.99,
                    'category_id': dessert_cat.id,
                    'is_available': True
                },
                {
                    'name': 'Kheer',
                    'description': 'Traditional rice pudding with cardamom and nuts',
                    'price': 4.99,
                    'category_id': dessert_cat.id,
                    'is_available': True
                },
                # Beverages
                {
                    'name': 'Mango Lassi',
                    'description': 'Traditional yogurt drink with mango',
                    'price': 4.99,
                    'category_id': beverage_cat.id,
                    'is_available': True
                },
                {
                    'name': 'Chai Tea',
                    'description': 'Spiced tea with milk',
                    'price': 2.99,
                    'category_id': beverage_cat.id,
                    'is_available': True
                }
            ]

            for item_data in menu_items_data:
                if not MenuItem.query.filter_by(name=item_data['name']).first():
                    menu_item = MenuItem(**item_data)
                    db.session.add(menu_item)
        
        print("Menu items created successfully")

        # Create tables
        tables_data = [
            {'number': 0, 'capacity': 1, 'is_occupied': False},  # Takeaway
            {'number': 1, 'capacity': 4, 'is_occupied': False},
            {'number': 2, 'capacity': 2, 'is_occupied': False},
            {'number': 3, 'capacity': 6, 'is_occupied': False},
            {'number': 4, 'capacity': 4, 'is_occupied': False},
            {'number': 5, 'capacity': 8, 'is_occupied': False},
            {'number': 6, 'capacity': 2, 'is_occupied': False}
        ]

        for table_data in tables_data:
            if not Table.query.filter_by(number=table_data['number']).first():
                table = Table(**table_data)
                db.session.add(table)

        db.session.commit()
        print("Sample data created successfully!")
        return True
        
    except Exception as e:
        print(f"Error creating sample data: {str(e)}")
        db.session.rollback()
        raise

# -------------------- DATABASE INITIALIZATION --------------------
def ensure_db_initialized():
    """Ensure database is initialized - works for both SQLite and Azure SQL"""
    try:
        print("Checking database initialization...")
        
        # Test database connection
        with db.engine.connect() as connection:
            result = connection.execute(text('SELECT 1'))
            result.fetchone()
        print("Database connection successful!")
        
        # Check if tables exist and have data
        table_count = Table.query.count()
        category_count = Category.query.count()
        menu_count = MenuItem.query.count()
        
        print(f"Found: Tables={table_count}, Categories={category_count}, MenuItems={menu_count}")
        
        # Create sample data if missing
        if table_count == 0 or category_count == 0 or menu_count == 0:
            print("Insufficient sample data found, creating...")
            create_sample_data()
            
        return True
            
    except Exception as e:
        print(f"Database not initialized: {str(e)}")
        try:
            print("Creating all database tables...")
            db.create_all()
            print("Tables created successfully")
            
            print("Adding sample data...")
            create_sample_data()
            print("Database initialized successfully!")
            return True
            
        except Exception as init_error:
            print(f"Error during database initialization: {str(init_error)}")
            return False

# Initialize database on startup
try:
    with app.app_context():
        ensure_db_initialized()
except Exception as e:
    print(f"Startup database initialization failed: {str(e)}")

# -------------------- FORMS --------------------
class MenuItemForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()])
    price = DecimalField('Price', validators=[DataRequired(), NumberRange(min=0.01)])
    category_id = SelectField('Category', coerce=int, validators=[DataRequired()])
    is_available = BooleanField('Available', default=True)
    image_url = StringField('Image URL')

class OrderForm(FlaskForm):
    table_id = SelectField('Table', coerce=int, validators=[DataRequired()])
    customer_name = StringField('Customer Name', validators=[DataRequired()])

class OrderItemForm(FlaskForm):
    menu_item_id = SelectField('Menu Item', coerce=int, validators=[DataRequired()])
    quantity = IntegerField('Quantity', validators=[DataRequired(), NumberRange(min=1)], default=1)

# -------------------- BASIC ROUTES --------------------
@app.route('/favicon.ico')
def favicon():
    try:
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    except:
        return '', 204

@app.route('/')
def index():
    try:
        return render_template('index.html')
    except Exception:
        return """
        <h1>🍽️ Ali Restaurant Management System</h1>
        <p>Welcome to Ali Restaurant! Your table management and ordering system is running.</p>
        <div style="margin: 20px 0;">
            <a href="/dashboard" style="margin-right: 15px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;">Dashboard</a>
            <a href="/menu" style="margin-right: 15px; padding: 10px 20px; background: #28a745; color: white; text-decoration: none; border-radius: 5px;">Menu</a>
            <a href="/orders" style="margin-right: 15px; padding: 10px 20px; background: #ffc107; color: black; text-decoration: none; border-radius: 5px;">Orders</a>
            <a href="/tables" style="padding: 10px 20px; background: #17a2b8; color: white; text-decoration: none; border-radius: 5px;">Tables</a>
        </div>
        """

@app.route('/test')
def test():
    """Test endpoint to verify app and database"""
    try:
        # Test database connection
        with db.engine.connect() as conn:
            result = conn.execute(text('SELECT 1'))
            result.fetchone()
        
        # Get counts
        table_count = Table.query.count()
        menu_count = MenuItem.query.count()
        order_count = Order.query.count()
        category_count = Category.query.count()
        
        db_type = 'Azure SQL' if 'sqlserver' in str(db.engine.url) or 'mssql' in str(db.engine.url) else 'SQLite'
        
        return f"""
        <h2>🚀 Ali Restaurant App - System Status</h2>
        <p><strong>Status:</strong> ✅ Running Successfully</p>
        <p><strong>Database:</strong> {db_type}</p>
        <p><strong>Tables:</strong> {table_count}</p>
        <p><strong>Categories:</strong> {category_count}</p>
        <p><strong>Menu Items:</strong> {menu_count}</p>
        <p><strong>Orders:</strong> {order_count}</p>
        <br>
        <a href="/dashboard">Go to Dashboard</a>
        """
    except Exception as e:
        return f"⚠️ App running but database error: {str(e)}<br><br><a href='/startup'>Initialize Database</a>"

# -------------------- DATABASE MANAGEMENT ROUTES --------------------
@app.route('/startup')
def startup():
    """Startup route to initialize database"""
    try:
        with app.app_context():
            print("Manual startup initiated...")
            db.create_all()
            create_sample_data()
            
            # Verify creation
            tables = Table.query.count()
            categories = Category.query.count()
            items = MenuItem.query.count()
            
            return f"""
            <h2>✅ Database Initialized Successfully!</h2>
            <p>Created:</p>
            <ul>
                <li>{tables} Tables</li>
                <li>{categories} Categories</li>
                <li>{items} Menu Items</li>
            </ul>
            <br>
            <a href="/dashboard">Go to Dashboard</a> |
            <a href="/debug/data">View Data</a>
            """
    except Exception as e:
        return f"""
        <h2>❌ Database Initialization Failed</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <br>
        <a href="/debug/connection">Test Connection</a>
        """

@app.route('/init-db-force')
def init_db_force():
    """Force database reinitialization"""
    try:
        print("Force reinitializing database...")
        db.drop_all()
        db.create_all()
        create_sample_data()
        return """
        <h2>🔄 Database Reset Complete!</h2>
        <p>All tables dropped and recreated with fresh sample data.</p>
        <br>
        <a href="/dashboard">Go to Dashboard</a>
        """
    except Exception as e:
        return f"""
        <h2>❌ Database Reset Failed</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        """

# -------------------- DASHBOARD --------------------
@app.route('/dashboard')
def dashboard():
    try:
        total_orders = Order.query.count()
        pending_orders = Order.query.filter_by(status='pending').count()
        preparing_orders = Order.query.filter_by(status='preparing').count()
        ready_orders = Order.query.filter_by(status='ready').count()
        total_revenue = db.session.query(db.func.sum(Order.total_amount)).scalar() or 0
        total_menu_items = MenuItem.query.count()
        total_tables = Table.query.count()
        occupied_tables = Table.query.filter_by(is_occupied=True).count()
        recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()

        stats = {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'preparing_orders': preparing_orders,
            'ready_orders': ready_orders,
            'total_revenue': float(total_revenue),
            'total_menu_items': total_menu_items,
            'total_tables': total_tables,
            'occupied_tables': occupied_tables,
            'recent_orders': recent_orders
        }
        return render_template('dashboard.html', stats=stats)
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return render_template('dashboard.html', stats={
            'total_orders': 0, 'pending_orders': 0, 'preparing_orders': 0, 'ready_orders': 0,
            'total_revenue': 0, 'total_menu_items': 0, 'total_tables': 0, 'occupied_tables': 0,
            'recent_orders': []
        })

# -------------------- MENU MANAGEMENT --------------------
@app.route('/menu')
def menu_list():
    try:
        menu_items = MenuItem.query.join(Category).all()
        categories = Category.query.all()
        available_tables = Table.query.filter_by(is_occupied=False).all()
        return render_template('menu.html', 
                             menu_items=menu_items, 
                             categories=categories,
                             tables=available_tables)
    except Exception as e:
        flash(f'Error loading menu: {str(e)}', 'error')
        return render_template('menu.html', menu_items=[], categories=[], tables=[])

@app.route('/menu/add', methods=['GET', 'POST'])
def add_menu_item():
    form = MenuItemForm()
    try:
        categories = Category.query.all()
        if not categories:
            flash('Please create at least one category first!', 'warning')
            return redirect(url_for('add_category'))
            
        form.category_id.choices = [(c.id, c.name) for c in categories]
        
        if form.validate_on_submit():
            menu_item = MenuItem(
                name=form.name.data,
                description=form.description.data,
                price=form.price.data,
                category_id=form.category_id.data,
                is_available=form.is_available.data,
                image_url=form.image_url.data if form.image_url.data else None
            )
            db.session.add(menu_item)
            db.session.commit()
            flash('Menu item added successfully!', 'success')
            return redirect(url_for('menu_list'))
    except Exception as e:
        flash(f'Error adding menu item: {str(e)}', 'error')
        db.session.rollback()
        
    return render_template('add_menu_item.html', form=form)

@app.route('/menu/edit/<int:id>', methods=['GET', 'POST'])
def edit_menu_item(id):
    menu_item = db.session.get(MenuItem, id)
    if not menu_item:
        flash('Menu item not found!', 'error')
        return redirect(url_for('menu_list'))
        
    form = MenuItemForm(obj=menu_item)
    
    try:
        form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
        
        if form.validate_on_submit():
            form.populate_obj(menu_item)
            db.session.commit()
            flash('Menu item updated successfully!', 'success')
            return redirect(url_for('menu_list'))
    except Exception as e:
        flash(f'Error updating menu item: {str(e)}', 'error')
        db.session.rollback()
        
    return render_template('add_menu_item.html', form=form, menu_item=menu_item)

@app.route('/menu/delete/<int:id>')
def delete_menu_item(id):
    try:
        menu_item = db.session.get(MenuItem, id)
        if not menu_item:
            flash('Menu item not found!', 'error')
            return redirect(url_for('menu_list'))
            
        # Check if menu item is used in any active orders
        active_orders = db.session.query(OrderItem).join(Order).filter(
            OrderItem.menu_item_id == id,
            Order.status.in_(['pending', 'preparing', 'ready'])
        ).count()
        
        if active_orders > 0:
            flash('Cannot delete menu item that is used in active orders!', 'error')
            return redirect(url_for('menu_list'))
            
        db.session.delete(menu_item)
        db.session.commit()
        flash('Menu item deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting menu item: {str(e)}', 'error')
        db.session.rollback()
    
    return redirect(url_for('menu_list'))

# -------------------- CATEGORIES MANAGEMENT --------------------
@app.route('/categories')
def categories_list():
    try:
        categories = Category.query.all()
        return render_template('categories.html', categories=categories)
    except Exception as e:
        flash(f'Error loading categories: {str(e)}', 'error')
        return render_template('categories.html', categories=[])

@app.route('/categories/add', methods=['GET', 'POST'])
def add_category():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            
            if not name:
                flash('Category name is required!', 'error')
                return render_template('add_category.html')
            
            existing_category = Category.query.filter_by(name=name).first()
            if existing_category:
                flash(f'Category "{name}" already exists!', 'error')
                return render_template('add_category.html')
            
            category = Category(name=name, description=description)
            db.session.add(category)
            db.session.commit()
            flash('Category added successfully!', 'success')
            return redirect(url_for('categories_list'))
        except Exception as e:
            flash(f'Error adding category: {str(e)}', 'error')
            db.session.rollback()
    
    return render_template('add_category.html')

# -------------------- ORDERS MANAGEMENT --------------------
@app.route('/orders')
def orders_list():
    try:
        orders = Order.query.order_by(Order.created_at.desc()).all()
        return render_template('orders.html', orders=orders)
    except Exception as e:
        flash(f'Error loading orders: {str(e)}', 'error')
        return render_template('orders.html', orders=[])

@app.route('/orders/add', methods=['GET', 'POST'])
def add_order():
    form = OrderForm()
    
    try:
        # Get available data
        available_tables = Table.query.filter_by(is_occupied=False).all()
        menu_items = MenuItem.query.filter_by(is_available=True).all()
        categories = Category.query.all()
        
        # Validate requirements
        if not available_tables:
            flash('No tables available! Please add tables or free up occupied tables.', 'warning')
            return redirect(url_for('tables_list'))
        
        if not menu_items:
            flash('No menu items available! Please add some menu items first.', 'warning')
            return redirect(url_for('add_menu_item'))
        
        # Set form choices
        form.table_id.choices = [(t.id, f'Table {t.number} (Capacity: {t.capacity})') for t in available_tables]
        
        if request.method == 'POST':            
            # Get form data
            customer_name = request.form.get('customer_name', '').strip()
            table_id = request.form.get('table_id')
            order_items_json = request.form.get('order_items', '[]')
            
            # Validation
            if not customer_name:
                return jsonify({'success': False, 'error': 'Customer name is required'})
            
            if not table_id:
                return jsonify({'success': False, 'error': 'Please select a table'})
            
            try:
                table_id = int(table_id)
                selected_table = db.session.get(Table, table_id)
                if not selected_table or selected_table.is_occupied:
                    return jsonify({'success': False, 'error': 'Selected table is not available'})
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid table selection'})
            
            # Parse order items
            try:
                order_items = json.loads(order_items_json) if order_items_json else []
            except json.JSONDecodeError:
                return jsonify({'success': False, 'error': 'Invalid order data'})
            
            if not order_items:
                return jsonify({'success': False, 'error': 'Please add at least one item to the order'})
            
            # Create the order
            try:
                order = Order(
                    table_id=table_id,
                    customer_name=customer_name,
                    status='pending',
                    total_amount=0
                )
                db.session.add(order)
                db.session.flush()  # Get order ID
                
                # Add order items
                total = 0
                for item_data in order_items:
                    menu_item = db.session.get(MenuItem, item_data['id'])
                    if menu_item:
                        order_item = OrderItem(
                            order_id=order.id,
                            menu_item_id=menu_item.id,
                            quantity=item_data['quantity'],
                            price=menu_item.price
                        )
                        db.session.add(order_item)
                        total += float(menu_item.price) * item_data['quantity']
                
                # Update order total and table status
                order.total_amount = total
                selected_table.is_occupied = True
                
                db.session.commit()
                flash('Order created successfully!', 'success')
                return jsonify({'success': True, 'order_id': order.id})
                
            except Exception as e:
                db.session.rollback()
                app.logger.error(f'Order creation error: {str(e)}')
                return jsonify({'success': False, 'error': f'Database error: {str(e)}'})
                
    except Exception as e:
        flash(f'Error loading order form: {str(e)}', 'error')
        db.session.rollback()
    
    return render_template('add_order.html', form=form, menu_items=menu_items, categories=categories)

@app.route('/orders/<int:id>')
def order_details(id):
    try:
        order = db.session.get(Order, id)
        if not order:
            flash('Order not found!', 'error')
            return redirect(url_for('orders_list'))
            
        menu_items = MenuItem.query.filter_by(is_available=True).all()
        return render_template('order_details.html', order=order, menu_items=menu_items)
    except Exception as e:
        flash(f'Error loading order details: {str(e)}', 'error')
        return redirect(url_for('orders_list'))

@app.route('/orders/<int:id>/add_item', methods=['POST'])
def add_order_item(id):
    try:
        order = db.session.get(Order, id)
        if not order:
            flash('Order not found!', 'error')
            return redirect(url_for('orders_list'))
            
        menu_item_id = request.form.get('menu_item_id')
        quantity = int(request.form.get('quantity', 1))

        menu_item = db.session.get(MenuItem, menu_item_id)
        if menu_item:
            existing_item = OrderItem.query.filter_by(
                order_id=order.id, 
                menu_item_id=menu_item.id
            ).first()
            
            if existing_item:
                existing_item.quantity += quantity
            else:
                order_item = OrderItem(
                    order_id=order.id,
                    menu_item_id=menu_item.id,
                    quantity=quantity,
                    price=menu_item.price
                )
                db.session.add(order_item)

            order.total_amount = float(order.total_amount) + float(menu_item.price * quantity)
            order.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Item added to order!', 'success')
        else:
            flash('Menu item not found!', 'error')
    except Exception as e:
        flash(f'Error adding item to order: {str(e)}', 'error')
        db.session.rollback()

    return redirect(url_for('order_details', id=id))

@app.route('/orders/<int:id>/update_status', methods=['POST'])
def update_order_status(id):
    try:
        order = db.session.get(Order, id)
        if not order:
            flash('Order not found!', 'error')
            return redirect(url_for('orders_list'))
            
        new_status = request.form.get('status')

        if new_status in ['pending', 'preparing', 'ready', 'delivered', 'cancelled']:
            order.status = new_status
            order.updated_at = datetime.utcnow()
            
            # Free table when order is completed
            if new_status in ['delivered', 'cancelled']:
                order.table.is_occupied = False
                
            db.session.commit()
            flash(f'Order status updated to {new_status}!', 'success')
        else:
            flash('Invalid status!', 'error')
    except Exception as e:
        flash(f'Error updating order status: {str(e)}', 'error')
        db.session.rollback()

    return redirect(url_for('orders_list'))

# -------------------- TABLES MANAGEMENT --------------------
@app.route('/tables')
def tables_list():
    try:
        tables = Table.query.order_by(Table.number).all()
        return render_template('tables.html', tables=tables)
    except Exception as e:
        flash(f'Error loading tables: {str(e)}', 'error')
        return render_template('tables.html', tables=[])

@app.route('/tables/add', methods=['GET', 'POST'])
def add_table():
    if request.method == 'POST':
        try:
            table_number = int(request.form.get('table_number', 0))
            capacity = int(request.form.get('capacity', 1))
            
            # Validation
            if table_number < 0:
                flash('Table number cannot be negative.', 'error')
                return render_template('add_table.html')
                
            if capacity < 1 or capacity > 20:
                flash('Capacity must be between 1 and 20 guests.', 'error')
                return render_template('add_table.html')
            
            existing_table = Table.query.filter_by(number=table_number).first()
            if existing_table:
                flash(f'Table {table_number} already exists! Please choose a different number.', 'error')
                return render_template('add_table.html')
            
            new_table = Table(
                number=table_number,
                capacity=capacity,
                is_occupied=False
            )
            db.session.add(new_table)
            db.session.commit()
            flash(f'Table {table_number} added successfully!', 'success')
            return redirect(url_for('tables_list'))
            
        except ValueError:
            flash('Please enter valid numbers for table number and capacity.', 'error')
        except Exception as e:
            flash(f'Error adding table: {str(e)}', 'error')
            db.session.rollback()
    
    return render_template('add_table.html')

@app.route('/tables/edit/<int:id>', methods=['GET', 'POST'])
def edit_table(id):
    table = db.session.get(Table, id)
    if not table:
        flash('Table not found!', 'error')
        return redirect(url_for('tables_list'))
    
    if request.method == 'POST':
        try:
            table_number = int(request.form.get('table_number', table.number))
            capacity = int(request.form.get('capacity', table.capacity))
            is_occupied = request.form.get('is_occupied') is not None
            
            # Validation
            if table_number < 0:
                flash('Table number cannot be negative.', 'error')
                return render_template('edit_table.html', table=table)
                
            if capacity < 1 or capacity > 20:
                flash('Capacity must be between 1 and 20 guests.', 'error')
                return render_template('edit_table.html', table=table)
            
            # Check if table number already exists (excluding current table)
            existing_table = Table.query.filter(
                Table.number == table_number, 
                Table.id != id
            ).first()
            
            if existing_table:
                flash(f'Table {table_number} already exists! Please choose a different number.', 'error')
                return render_template('edit_table.html', table=table)
            
            # Update table
            table.number = table_number
            table.capacity = capacity
            table.is_occupied = is_occupied
            
            db.session.commit()
            flash(f'Table {table_number} updated successfully!', 'success')
            return redirect(url_for('tables_list'))
            
        except ValueError:
            flash('Please enter valid numbers for table number and capacity.', 'error')
        except Exception as e:
            flash(f'Error updating table: {str(e)}', 'error')
            db.session.rollback()
    
    return render_template('edit_table.html', table=table)

@app.route('/tables/delete/<int:id>')
def delete_table(id):
    try:
        table = db.session.get(Table, id)
        if not table:
            flash('Table not found!', 'error')
            return redirect(url_for('tables_list'))
        
        active_orders = Order.query.filter(
            Order.table_id == id,
            Order.status.in_(['pending', 'preparing', 'ready'])
        ).count()
        
        if active_orders > 0:
            flash(f'Cannot delete table {table.number}. It has active orders.', 'error')
        else:
            db.session.delete(table)
            db.session.commit()
            flash(f'Table {table.number} deleted successfully!', 'success')
            
    except Exception as e:
        flash(f'Error deleting table: {str(e)}', 'error')
        db.session.rollback()
    
    return redirect(url_for('tables_list'))

# -------------------- API ENDPOINTS --------------------
@app.route('/api/dashboard')
def api_dashboard():
    try:
        total_orders = Order.query.count()
        pending_orders = Order.query.filter_by(status='pending').count()
        total_revenue = db.session.query(db.func.sum(Order.total_amount)).scalar() or 0
        total_menu_items = MenuItem.query.count()

        return jsonify({
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'total_revenue': float(total_revenue),
            'total_menu_items': total_menu_items
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/menu')
def api_menu():
    try:
        menu_items = MenuItem.query.join(Category).all()
        return jsonify([{
            'id': item.id,
            'name': item.name,
            'description': item.description,
            'price': float(item.price),
            'category': item.category.name if item.category else 'Unknown',
            'available': item.is_available
        } for item in menu_items])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tables')
def api_tables():
    try:
        tables = Table.query.order_by(Table.number).all()
        return jsonify([{
            'id': table.id,
            'number': table.number,
            'capacity': table.capacity,
            'is_occupied': table.is_occupied
        } for table in tables])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/orders')
def api_orders():
    try:
        orders = Order.query.order_by(Order.created_at.desc()).all()
        return jsonify([{
            'id': order.id,
            'customer_name': order.customer_name,
            'table_number': order.table.number,
            'status': order.status,
            'total_amount': float(order.total_amount),
            'created_at': order.created_at.isoformat(),
            'items_count': len(order.items)
        } for order in orders])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# -------------------- DEBUG ROUTES --------------------
@app.route('/debug/data')
def debug_data():
    """Debug route to check database contents"""
    try:
        tables = Table.query.all()
        categories = Category.query.all()
        menu_items = MenuItem.query.all()
        orders = Order.query.all()
        
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        db_type = 'Azure SQL' if any(x in db_uri.lower() for x in ['sqlserver', 'mssql', 'database.windows.net']) else 'SQLite'
        
        return f"""
        <h2>Database Debug Information</h2>
        
        <h3>Connection Info:</h3>
        <p><strong>Database Type:</strong> {db_type}</p>
        <p><strong>Connection:</strong> {'Azure SQL Database' if 'database.windows.net' in db_uri else 'Local SQLite'}</p>
        
        <h3>Data Summary:</h3>
        <ul>
            <li><strong>Tables:</strong> {len(tables)}</li>
            <li><strong>Categories:</strong> {len(categories)}</li>
            <li><strong>Menu Items:</strong> {len(menu_items)}</li>
            <li><strong>Orders:</strong> {len(orders)}</li>
        </ul>
        
        <h3>Tables ({len(tables)}):</h3>
        <ul>
        {''.join([f"<li>Table {t.number}: capacity {t.capacity}, {'occupied' if t.is_occupied else 'available'}</li>" for t in tables])}
        </ul>
        
        <h3>Categories ({len(categories)}):</h3>
        <ul>
        {''.join([f"<li>{c.name}: {c.description}</li>" for c in categories])}
        </ul>
        
        <h3>Menu Items ({len(menu_items)}):</h3>
        <ul>
        {''.join([f"<li>{item.name}: ${item.price} ({item.category.name if item.category else 'No category'})</li>" for item in menu_items])}
        </ul>
        
        <h3>Recent Orders ({len(orders)}):</h3>
        <ul>
        {''.join([f"<li>Order #{o.id}: {o.customer_name} at Table {o.table.number}, Status: {o.status}, Total: ${o.total_amount}</li>" for o in orders[-10:]])}
        </ul>
        
        <br>
        <div style="margin: 20px 0;">
            <a href="/dashboard" style="margin-right: 10px; padding: 8px 16px; background: #007bff; color: white; text-decoration: none; border-radius: 4px;">Dashboard</a>
            <a href="/orders" style="margin-right: 10px; padding: 8px 16px; background: #28a745; color: white; text-decoration: none; border-radius: 4px;">Orders</a>
            <a href="/menu" style="margin-right: 10px; padding: 8px 16px; background: #ffc107; color: black; text-decoration: none; border-radius: 4px;">Menu</a>
            <a href="/tables" style="padding: 8px 16px; background: #17a2b8; color: white; text-decoration: none; border-radius: 4px;">Tables</a>
        </div>
        """
    except Exception as e:
        return f"""
        <h2>Database Access Error</h2>
        <p><strong>Error:</strong> {str(e)}</p>
        <br>
        <a href="/startup">Initialize Database</a> |
        <a href="/init-db-force">Force Reset Database</a> |
        <a href="/debug/connection">Test Connection</a>
        """

@app.route('/debug/connection')
def debug_connection():
    """Debug database connection"""
    try:
        # Test connection
        with db.engine.connect() as connection:
            result = connection.execute(text('SELECT 1 as test'))
            test_value = result.fetchone()[0]
        
        # Get database info
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        
        # Determine database type
        if 'database.windows.net' in db_uri or 'sqlserver' in db_uri or 'mssql' in db_uri:
            db_type = 'Azure SQL Database'
            connection_info = 'Connected to Azure SQL Server: alidata.database.windows.net'
        elif 'sqlite' in db_uri:
            db_type = 'SQLite'
            connection_info = f'SQLite database file: {db_uri.replace("sqlite:///", "")}'
        else:
            db_type = 'Unknown'
            connection_info = 'Unknown database type'
        
        # Test table queries
        table_count = Table.query.count()
        category_count = Category.query.count()
        menu_count = MenuItem.query.count()
        order_count = Order.query.count()
        
        return f"""
        <h2>Database Connection Test</h2>
        <p><strong>Status:</strong> ✅ Connected Successfully</p>
        <p><strong>Test Query Result:</strong> {test_value}</p>
        <p><strong>Database Type:</strong> {db_type}</p>
        <p><strong>Connection Info:</strong> {connection_info}</p>
        
        <h3>Table Verification:</h3>
        <ul>
            <li><strong>Tables:</strong> {table_count} records</li>
            <li><strong>Categories:</strong> {category_count} records</li>
            <li><strong>Menu Items:</strong> {menu_count} records</li>
            <li><strong>Orders:</strong> {order_count} records</li>
        </ul>
        
        <h3>Next Steps:</h3>
        <div style="margin: 20px 0;">
            <a href="/debug/data" style="margin-right: 10px; padding: 8px 16px; background: #28a745; color: white; text-decoration: none; border-radius: 4px;">View All Data</a>
            <a href="/dashboard" style="margin-right: 10px; padding: 8px 16px; background: #007bff; color: white; text-decoration: none; border-radius: 4px;">Go to Dashboard</a>
            <a href="/orders/add" style="padding: 8px 16px; background: #ffc107; color: black; text-decoration: none; border-radius: 4px;">Test Order Creation</a>
        </div>
        """
    except Exception as e:
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        masked_uri = db_uri.split('@')[0] + '@***' if '@' in db_uri else db_uri[:50] + '...'
        
        return f"""
        <h2>Database Connection Test</h2>
        <p><strong>Status:</strong> ❌ Connection Failed</p>
        <p><strong>Error:</strong> {str(e)}</p>
        <p><strong>Connection String:</strong> {masked_uri}</p>
        
        <h3>Troubleshooting Steps:</h3>
        <ol>
            <li>Verify your Azure SQL Database is running</li>
            <li>Check connection string in App Service configuration</li>
            <li>Ensure firewall allows Azure services</li>
            <li>Verify username and password are correct</li>
        </ol>
        
        <h3>Try These:</h3>
        <div style="margin: 20px 0;">
            <a href="/startup" style="margin-right: 10px; padding: 8px 16px; background: #28a745; color: white; text-decoration: none; border-radius: 4px;">Initialize Database</a>
            <a href="/init-db-force" style="padding: 8px 16px; background: #dc3545; color: white; text-decoration: none; border-radius: 4px;">Force Reset</a>
        </div>
        """

# -------------------- ERROR HANDLERS --------------------
@app.errorhandler(404)
def not_found_error(error):
    try:
        return render_template('404.html'), 404
    except Exception:
        return '''
        <h1>404 - Page Not Found</h1>
        <p>The requested page could not be found.</p>
        <br>
        <a href="/">Go Home</a> | 
        <a href="/dashboard">Dashboard</a>
        ''', 404

@app.errorhandler(500)
def internal_error(error):
    try:
        db.session.rollback()
        return render_template('500.html'), 500
    except Exception:
        return '''
        <h1>500 - Internal Server Error</h1>
        <p>Something went wrong on our end.</p>
        <br>
        <a href="/">Go Home</a> | 
        <a href="/debug/connection">Test Database</a> |
        <a href="/startup">Initialize Database</a>
        ''', 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle all other exceptions"""
    app.logger.error(f'Unhandled exception: {str(e)}')
    try:
        db.session.rollback()
        return render_template('500.html'), 500
    except Exception:
        return f'''
        <h1>500 - Application Error</h1>
        <p>Error: {str(e)}</p>
        <br>
        <a href="/">Go Home</a> | 
        <a href="/debug/connection">Test Database</a>
        ''', 500

# -------------------- DEVELOPMENT HELPER --------------------
def init_db_local():
    """Initialize database for local development"""
    try:
        with app.app_context():
            db.create_all()
            create_sample_data()
            print("Local database initialized successfully!")
            return True
    except Exception as e:
        print(f"Error initializing local database: {str(e)}")
        return False

# -------------------- MAIN APPLICATION --------------------
if __name__ == '__main__':
    # Initialize database for local development
    try:
        if not os.environ.get('WEBSITE_SITE_NAME'):  # Not running on Azure
            init_db_local()
    except Exception as e:
        print(f"Warning: Could not initialize database locally: {str(e)}")
    
    # Get configuration
    port = int(os.environ.get('PORT', 8000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    print(f"Starting Ali Restaurant Management System")
    print(f"Port: {port}")
    print(f"Debug mode: {debug_mode}")
    print(f"Database: {'Azure SQL' if 'database.windows.net' in app.config['SQLALCHEMY_DATABASE_URI'] else 'SQLite'}")
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
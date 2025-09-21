from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField, BooleanField, IntegerField
from wtforms.validators import DataRequired, NumberRange
from datetime import datetime
import os
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'

# Database Configuration - Azure SQL Database
if 'SQLAZURECONNSTR_DefaultConnection' in os.environ:
    # Production - Azure SQL Database
    connection_string = os.environ['SQLAZURECONNSTR_DefaultConnection']
    app.config['SQLALCHEMY_DATABASE_URI'] = connection_string
else:
    # Development - SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///restaurant.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_recycle': 300,
    'pool_pre_ping': True
}

db = SQLAlchemy(app)

# -------------------- MODELS --------------------
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    menu_items = db.relationship('MenuItem', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'

class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    image_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<MenuItem {self.name}>'

class Table(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)
    orders = db.relationship('Order', backref='table', lazy=True)

    def __repr__(self):
        return f'<Table {self.number}>'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('table.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')
    total_amount = db.Column(db.Numeric(10, 2), default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.id} - {self.customer_name}>'

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    menu_item = db.relationship('MenuItem', backref='order_items')

    def get_total_price(self):
        return float(self.quantity * self.price)

    def __repr__(self):
        return f'<OrderItem {self.quantity}x {self.menu_item.name if self.menu_item else "Unknown"}>'

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

# -------------------- ROUTES --------------------
@app.route('/favicon.ico')
def favicon():
    try:
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    except:
        return '', 204

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    try:
        total_orders = Order.query.count()
        pending_orders = Order.query.filter_by(status='pending').count()
        total_revenue = db.session.query(db.func.sum(Order.total_amount)).scalar() or 0
        total_menu_items = MenuItem.query.count()
        recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()

        stats = {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'total_revenue': float(total_revenue),
            'total_menu_items': total_menu_items,
            'recent_orders': recent_orders
        }
        return render_template('dashboard.html', stats=stats)
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return render_template('dashboard.html', stats={
            'total_orders': 0, 'pending_orders': 0, 
            'total_revenue': 0, 'total_menu_items': 0, 
            'recent_orders': []
        })

# ---- Menu Management ----
@app.route('/menu')
def menu_list():
    try:
        menu_items = MenuItem.query.all()
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
    menu_item = MenuItem.query.get_or_404(id)
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
        menu_item = MenuItem.query.get_or_404(id)
        db.session.delete(menu_item)
        db.session.commit()
        flash('Menu item deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting menu item: {str(e)}', 'error')
    
    return redirect(url_for('menu_list'))

# ---- Categories Management ----
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

# ---- Orders Management ----
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
        # Get available tables and menu items
        available_tables = Table.query.filter_by(is_occupied=False).all()
        menu_items = MenuItem.query.filter_by(is_available=True).all()
        categories = Category.query.all()
        
        # Check if we have required data
        if not available_tables:
            flash('No tables available! Please add tables or free up occupied tables.', 'warning')
            return redirect(url_for('tables_list'))
        
        if not menu_items:
            flash('No menu items available! Please add some menu items first.', 'warning')
            return redirect(url_for('add_menu_item'))
        
        # Set form choices
        form.table_id.choices = [(t.id, f'Table {t.number} (Capacity: {t.capacity})') for t in available_tables]
        
        if request.method == 'POST':
            # Debug logging
            print("=== ORDER FORM DEBUG ===")
            print(f"Customer name: '{request.form.get('customer_name')}'")
            print(f"Table ID: '{request.form.get('table_id')}'")
            print(f"Order items: '{request.form.get('order_items')}'")
            print(f"Total amount: '{request.form.get('total_amount')}'")
            print(f"CSRF token present: {bool(request.form.get('csrf_token'))}")
            print(f"Form errors: {form.errors}")
            print("========================")
            
            # Manual validation to provide better error messages
            customer_name = request.form.get('customer_name', '').strip()
            table_id = request.form.get('table_id')
            order_items_json = request.form.get('order_items', '[]')
            total_amount_str = request.form.get('total_amount', '0')
            
            # Check required fields
            if not customer_name:
                return jsonify({'success': False, 'error': 'Customer name is required'})
            
            if not table_id:
                return jsonify({'success': False, 'error': 'Please select a table'})
            
            try:
                table_id = int(table_id)
                selected_table = Table.query.get(table_id)
                if not selected_table:
                    return jsonify({'success': False, 'error': 'Selected table does not exist'})
                if selected_table.is_occupied:
                    return jsonify({'success': False, 'error': 'Selected table is already occupied'})
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid table selection'})
            
            # Parse order items
            try:
                order_items = json.loads(order_items_json) if order_items_json else []
                total_amount = float(total_amount_str) if total_amount_str else 0
            except (json.JSONDecodeError, ValueError) as e:
                return jsonify({'success': False, 'error': f'Invalid order data: {str(e)}'})
            
            if not order_items:
                return jsonify({'success': False, 'error': 'Please add at least one item to the order'})
            
            # Create the order
            try:
                order = Order(
                    table_id=table_id,
                    customer_name=customer_name,
                    status='pending',
                    total_amount=0  # Will be calculated from items
                )
                db.session.add(order)
                db.session.flush()  # Get the order ID
                
                # Add order items and calculate total
                calculated_total = 0
                for item_data in order_items:
                    menu_item = MenuItem.query.get(item_data['id'])
                    if menu_item:
                        order_item = OrderItem(
                            order_id=order.id,
                            menu_item_id=menu_item.id,
                            quantity=item_data['quantity'],
                            price=menu_item.price
                        )
                        db.session.add(order_item)
                        calculated_total += float(menu_item.price) * item_data['quantity']
                
                # Update order total and mark table as occupied
                order.total_amount = calculated_total
                selected_table.is_occupied = True
                
                db.session.commit()
                flash('Order created successfully!', 'success')
                return jsonify({'success': True, 'order_id': order.id})
                
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': f'Database error: {str(e)}'})
                
    except Exception as e:
        flash(f'Error loading order form: {str(e)}', 'error')
        db.session.rollback()
    
    return render_template('add_order.html', form=form, menu_items=menu_items, categories=categories)

@app.route('/orders/<int:id>')
def order_details(id):
    try:
        order = Order.query.get_or_404(id)
        menu_items = MenuItem.query.filter_by(is_available=True).all()
        return render_template('order_details.html', order=order, menu_items=menu_items)
    except Exception as e:
        flash(f'Error loading order details: {str(e)}', 'error')
        return redirect(url_for('orders_list'))

@app.route('/orders/<int:id>/add_item', methods=['POST'])
def add_order_item(id):
    try:
        order = Order.query.get_or_404(id)
        menu_item_id = request.form.get('menu_item_id')
        quantity = int(request.form.get('quantity', 1))

        menu_item = MenuItem.query.get(menu_item_id)
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
        order = Order.query.get_or_404(id)
        new_status = request.form.get('status')

        if new_status in ['pending', 'preparing', 'ready', 'delivered', 'cancelled']:
            order.status = new_status
            order.updated_at = datetime.utcnow()
            
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

# ---- Tables Management ----
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
    table = Table.query.get_or_404(id)
    
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
        table = Table.query.get_or_404(id)
        
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

# -------------------- DEBUG ROUTES --------------------
@app.route('/debug/data')
def debug_data():
    """Debug route to check database contents"""
    try:
        tables = Table.query.all()
        categories = Category.query.all()
        menu_items = MenuItem.query.all()
        orders = Order.query.all()
        
        return f"""
        <h2>Database Debug Information</h2>
        
        <h3>Tables ({len(tables)}):</h3>
        <ul>
        {''.join([f"<li>ID: {t.id}, Table {t.number}: capacity {t.capacity}, occupied: {t.is_occupied}</li>" for t in tables])}
        </ul>
        
        <h3>Categories ({len(categories)}):</h3>
        <ul>
        {''.join([f"<li>ID: {c.id}, {c.name}</li>" for c in categories])}
        </ul>
        
        <h3>Menu Items ({len(menu_items)}):</h3>
        <ul>
        {''.join([f"<li>ID: {item.id}, {item.name} (${item.price}) - Category: {item.category_id}, Available: {item.is_available}</li>" for item in menu_items])}
        </ul>
        
        <h3>Orders ({len(orders)}):</h3>
        <ul>
        {''.join([f"<li>ID: {o.id}, {o.customer_name} - Table {o.table.number}, Status: {o.status}, Total: ${o.total_amount}</li>" for o in orders])}
        </ul>
        
        <br>
        <a href="/">Home</a> | 
        <a href="/orders/add">Add Order</a> | 
        <a href="/tables/add">Add Table</a> | 
        <a href="/categories/add">Add Category</a>
        """
    except Exception as e:
        return f"Error: {str(e)}"

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
        menu_items = MenuItem.query.all()
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

# -------------------- SAMPLE DATA --------------------
def create_sample_data():
    try:
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

        # Create menu items
        main_course_cat = Category.query.filter_by(name='Main Course').first()
        appetizer_cat = Category.query.filter_by(name='Appetizers').first()
        dessert_cat = Category.query.filter_by(name='Desserts').first()
        beverage_cat = Category.query.filter_by(name='Beverages').first()

        if main_course_cat and appetizer_cat and dessert_cat and beverage_cat:
            menu_items_data = [
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
                    'name': 'Gulab Jamun',
                    'description': 'Sweet milk dumplings in sugar syrup',
                    'price': 5.99,
                    'category_id': dessert_cat.id,
                    'is_available': True
                },
                {
                    'name': 'Mango Lassi',
                    'description': 'Traditional yogurt drink with mango',
                    'price': 4.99,
                    'category_id': beverage_cat.id,
                    'is_available': True
                }
            ]

            for item_data in menu_items_data:
                if not MenuItem.query.filter_by(name=item_data['name']).first():
                    menu_item = MenuItem(**item_data)
                    db.session.add(menu_item)

        # Create tables
        tables_data = [
            {'number': 0, 'capacity': 1, 'is_occupied': False},  # Takeaway table
            {'number': 1, 'capacity': 4, 'is_occupied': False},
            {'number': 2, 'capacity': 2, 'is_occupied': False},
            {'number': 3, 'capacity': 6, 'is_occupied': False},
            {'number': 4, 'capacity': 4, 'is_occupied': False},
            {'number': 5, 'capacity': 8, 'is_occupied': False}
        ]

        for table_data in tables_data:
            if not Table.query.filter_by(number=table_data['number']).first():
                table = Table(**table_data)
                db.session.add(table)

        db.session.commit()
        print("Sample data created successfully!")
        
    except Exception as e:
        print(f"Error creating sample data: {str(e)}")
        db.session.rollback()

# -------------------- ERROR HANDLERS --------------------
@app.errorhandler(404)
def not_found_error(error):
    try:
        return render_template('404.html'), 404
    except Exception:
        return '<h1>404 - Page Not Found</h1><p>The requested page could not be found.</p>', 404

@app.errorhandler(500)
def internal_error(error):
    try:
        db.session.rollback()
        return render_template('500.html'), 500
    except Exception:
        return '<h1>500 - Internal Server Error</h1><p>Something went wrong on our end.</p>', 500

# -------------------- INITIALIZATION --------------------
def init_db():
    try:
        with app.app_context():
            db.create_all()
            create_sample_data()
            print("Database initialized successfully!")
    except Exception as e:
        print(f"Error initializing database: {str(e)}")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 8000))
    # Default debug to false for Azure production
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)

# app.py
# This is your main application file. All backend logic resides here.

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
from passlib.hash import sha256_crypt
from functools import wraps # Import moved to the top
import config # Importing from config.py

# App initialization
app = Flask(__name__)

# Secret Key for session management
app.config['SECRET_KEY'] = 'your_very_secret_key_for_world_class_app'

# DB configuration from config.py file
app.config['MYSQL_HOST'] = config.MYSQL_HOST
app.config['MYSQL_USER'] = config.MYSQL_USER
app.config['MYSQL_PASSWORD'] = config.MYSQL_PASSWORD
app.config['MYSQL_DB'] = config.MYSQL_DB
app.config['MYSQL_CURSORCLASS'] = 'DictCursor' # To get data as dictionaries

# Initialize MySQL
mysql = MySQL(app)

# ==================================================
# ===          Decorator Functions             ===
# ==================================================

def is_logged_in(f):
    """Decorator to check if user is logged in"""
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            flash('Please log in to view this page.', 'danger')
            return redirect(url_for('login'))
    return wrap

def is_admin(f):
    """Decorator to check if user is admin"""
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session and session['role'] == 'admin':
            return f(*args, **kwargs)
        else:
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
    return wrap

# ==================================================
# ===          Main & Auth Routes              ===
# ==================================================

@app.route('/')
def home():
    """Home Page"""
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User Registration"""
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        password = sha256_crypt.encrypt(str(request.form['password']))
        cur = mysql.connection.cursor()
        result = cur.execute("SELECT * FROM users WHERE email = %s", [email])
        if result > 0:
            flash('An account with this email already exists.', 'danger')
            cur.close()
            return redirect(url_for('register'))
        cur.execute("INSERT INTO users(fullname, email, password) VALUES(%s, %s, %s)", (fullname, email, password))
        mysql.connection.commit()
        cur.close()
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User Login"""
    if request.method == 'POST':
        email = request.form['email']
        password_candidate = request.form['password']
        cur = mysql.connection.cursor()
        result = cur.execute("SELECT * FROM users WHERE email = %s", [email])
        if result > 0:
            data = cur.fetchone()
            cur.close()
            password = data['password']
            if sha256_crypt.verify(password_candidate, password):
                session['logged_in'] = True
                session['user_id'] = data['id']
                session['fullname'] = data['fullname']
                session['role'] = data['role']
                flash('You have successfully logged in.', 'success')
                if data['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid password.', 'danger')
        else:
            cur.close()
            flash('No user found with that email.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@is_logged_in
def logout():
    """User Logout"""
    session.clear()
    flash('You have successfully logged out.', 'success')
    return redirect(url_for('login'))

# ==================================================
# ===          User Facing Routes              ===
# ==================================================

@app.route('/dashboard')
def dashboard():
    """User Dashboard - Shows events with filtering"""
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM categories ORDER BY name")
    categories = cur.fetchall()
    query = """
        SELECT e.id, e.name, e.start_time, e.image_url, v.name as venue_name, c.name as category_name
        FROM events e
        LEFT JOIN venues v ON e.venue_id = v.id
        LEFT JOIN categories c ON e.category_id = c.id
    """
    category_filter = request.args.get('category')
    if category_filter and category_filter.isdigit():
        query += " WHERE c.id = %s"
        cur.execute(query, [category_filter])
    else:
        cur.execute(query)
    events = cur.fetchall()
    cur.close()
    return render_template('dashboard.html', events=events, categories=categories)

@app.route('/event/<int:id>')
def event_detail(id):
    """Shows details for a single event"""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT e.*, v.name as venue_name, v.address, c.name as category_name
        FROM events e
        LEFT JOIN venues v ON e.venue_id = v.id
        LEFT JOIN categories c ON e.category_id = c.id
        WHERE e.id = %s
    """, [id])
    event = cur.fetchone()
    if not event:
        flash('Event not found.', 'danger')
        return redirect(url_for('dashboard'))
    cur.execute("SELECT * FROM tickets WHERE event_id = %s", [id])
    tickets = cur.fetchall()
    cur.execute("""
        SELECT r.rating, r.comment, r.created_at, u.fullname
        FROM reviews r JOIN users u ON r.user_id = u.id
        WHERE r.event_id = %s ORDER BY r.created_at DESC
    """, [id])
    reviews = cur.fetchall()
    cur.close()
    return render_template('event_detail.html', event=event, tickets=tickets, reviews=reviews)

@app.route('/book_ticket/<int:event_id>', methods=['POST'])
@is_logged_in
def book_ticket(event_id):
    """Handles ticket booking"""
    ticket_id = request.form['ticket_id']
    quantity = int(request.form.get('quantity', 1))
    user_id = session['user_id']
    cur = mysql.connection.cursor()
    cur.execute("SELECT price FROM tickets WHERE id = %s", [ticket_id])
    ticket = cur.fetchone()
    if not ticket:
        flash("Invalid ticket selected.", "danger")
        return redirect(url_for('event_detail', id=event_id))
    total_price = ticket['price'] * quantity
    cur.execute("""
        INSERT INTO bookings (user_id, event_id, ticket_id, quantity, total_price, status)
        VALUES (%s, %s, %s, %s, %s, 'confirmed')
    """, (user_id, event_id, ticket_id, quantity, total_price))
    mysql.connection.commit()
    cur.close()
    flash('Your ticket booking was successful!', 'success')
    return redirect(url_for('my_bookings'))

@app.route('/my_bookings')
@is_logged_in
def my_bookings():
    """Shows all bookings for the current user"""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT e.name as event_name, t.type as ticket_type, b.quantity, b.total_price, b.status, b.booked_at
        FROM bookings b
        JOIN events e ON b.event_id = e.id
        JOIN tickets t ON b.ticket_id = t.id
        WHERE b.user_id = %s
        ORDER BY b.booked_at DESC
    """, [session['user_id']])
    bookings = cur.fetchall()
    cur.close()
    return render_template('my_bookings.html', bookings=bookings)

@app.route('/profile', methods=['GET', 'POST'])
@is_logged_in
def profile():
    """User Profile View and Update"""
    user_id = session['user_id']
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        fullname = request.form['fullname']
        email = request.form['email']
        cur.execute("UPDATE users SET fullname = %s, email = %s WHERE id = %s", (fullname, email, user_id))
        mysql.connection.commit()
        session['fullname'] = fullname
        flash('Profile updated successfully.', 'success')
        cur.close()
        return redirect(url_for('profile'))
    cur.execute("SELECT * FROM users WHERE id = %s", [user_id])
    user = cur.fetchone()
    cur.close()
    return render_template('profile.html', user=user)

# ==================================================
# ===             Admin Routes                 ===
# ==================================================

@app.route('/admin')
@is_admin
def admin_dashboard():
    """Admin Dashboard Hub"""
    return render_template('admin/admin_dashboard.html')

@app.route('/admin/bookings')
@is_admin
def admin_bookings():
    """Admin view for all bookings"""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT b.id, u.fullname, e.name as event_name, t.type as ticket_type, b.status, b.booked_at
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN events e ON b.event_id = e.id
        JOIN tickets t ON b.ticket_id = t.id
        ORDER BY b.booked_at DESC
    """)
    bookings = cur.fetchall()
    cur.close()
    return render_template('admin/admin_bookings.html', bookings=bookings)

# CRUD for Events
@app.route('/admin/events')
@is_admin
def admin_events():
    """Read all events for admin"""
    cur = mysql.connection.cursor()
    cur.execute("SELECT e.id, e.name, e.start_time FROM events e ORDER BY e.start_time DESC")
    events = cur.fetchall()
    cur.close()
    return render_template('admin/admin_events.html', events=events)

@app.route('/admin/event/add', methods=['GET', 'POST'])
@is_admin
def add_event():
    """Create a new event"""
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        venue_id = request.form['venue_id']
        category_id = request.form['category_id']
        image_url = request.form.get('image_url', '')
        cur.execute("""
            INSERT INTO events(name, description, start_time, end_time, venue_id, category_id, image_url, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, description, start_time, end_time, venue_id, category_id, image_url, session['user_id']))
        mysql.connection.commit()
        cur.close()
        flash('Event created successfully', 'success')
        return redirect(url_for('admin_events'))

    cur.execute("SELECT id, name FROM venues")
    venues = cur.fetchall()
    cur.execute("SELECT id, name FROM categories")
    categories = cur.fetchall()
    cur.close()
    return render_template('admin/add_event.html', venues=venues, categories=categories)

@app.route('/admin/event/edit/<int:id>', methods=['GET', 'POST'])
@is_admin
def edit_event(id):
    """Update an existing event"""
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        venue_id = request.form['venue_id']
        category_id = request.form['category_id']
        image_url = request.form.get('image_url', '')
        cur.execute("""
            UPDATE events SET name=%s, description=%s, start_time=%s, end_time=%s, venue_id=%s, category_id=%s, image_url=%s
            WHERE id=%s
        """, (name, description, start_time, end_time, venue_id, category_id, image_url, id))
        mysql.connection.commit()
        cur.close()
        flash('Event updated successfully', 'success')
        return redirect(url_for('admin_events'))

    cur.execute("SELECT * FROM events WHERE id = %s", [id])
    event = cur.fetchone()
    cur.execute("SELECT id, name FROM venues")
    venues = cur.fetchall()
    cur.execute("SELECT id, name FROM categories")
    categories = cur.fetchall()
    cur.close()
    return render_template('admin/edit_event.html', event=event, venues=venues, categories=categories)

@app.route('/admin/event/delete/<int:id>', methods=['POST'])
@is_admin
def delete_event(id):
    """Delete an event"""
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM events WHERE id = %s", [id])
    mysql.connection.commit()
    cur.close()
    flash('Event deleted successfully', 'danger')
    return redirect(url_for('admin_events'))

# Run the app
if __name__ == '__main__':
    app.run(debug=True)

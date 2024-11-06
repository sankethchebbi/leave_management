from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import and_
import math

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///leave_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'  # Replace with a secure random key
db = SQLAlchemy(app)

# Admin Credentials
app.config['ADMIN_USERNAME'] = 'admin'
app.config['ADMIN_PASSWORD'] = 'password123'

# Database Models
class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    leaves = db.relationship('Leave', backref='employee', lazy=True)

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)

class Replacement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_on_leave_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    replacement_employee_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)

# Create the database tables
with app.app_context():
    db.create_all()

# Helper function to calculate the 33% limit
def is_within_limit(date):
    total_employees = Employee.query.count()
    leaves_on_date = Leave.query.filter_by(date=date).count()
    if total_employees == 0:
        return True
    return (leaves_on_date / total_employees) < 0.33

# Routes
@app.route('/')
def index():
    employees = Employee.query.all()
    return render_template('index.html', employees=employees)

@app.route('/add_employee', methods=['POST'])
def add_employee():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    name = request.form['name']
    if not name:
        return redirect(url_for('index'))
    new_employee = Employee(name=name)
    db.session.add(new_employee)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/calendar/<int:employee_id>')
def calendar(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    employees = Employee.query.filter(Employee.id != employee_id).all()
    return render_template('calendar.html', employee=employee, employees=employees)

@app.route('/request_leave', methods=['POST'])
def request_leave():
    data = request.get_json()
    employee_id = data['employee_id']
    dates = data['dates']
    replacement_employee_id = int(data['replacement_employee_id'])

    employee = Employee.query.get(employee_id)
    replacement_employee = Employee.query.get(replacement_employee_id)

    approved_dates = []
    declined_dates = []

    for date_str in dates:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Check 33% limit
        if not is_within_limit(date):
            declined_dates.append(date_str)
            continue

        # Check if replacement is on leave on the same day
        replacement_on_leave = Leave.query.filter_by(employee_id=replacement_employee_id, date=date).first()
        if replacement_on_leave:
            declined_dates.append(date_str)
            continue

        # Check for mutual replacements on the same day
        mutual_replacement = Replacement.query.filter(
            and_(
                Replacement.employee_on_leave_id == replacement_employee_id,
                Replacement.replacement_employee_id == employee_id,
                Replacement.date == date
            )
        ).first()
        if mutual_replacement:
            declined_dates.append(date_str)
            continue

        # Check if replacement is already assigned on the same day
        replacement_assigned = Replacement.query.filter(
            and_(
                Replacement.replacement_employee_id == replacement_employee_id,
                Replacement.date == date
            )
        ).first()
        if replacement_assigned:
            declined_dates.append(date_str)
            continue

        # Approve leave and assign replacement
        new_leave = Leave(date=date, employee_id=employee_id)
        db.session.add(new_leave)
        new_replacement = Replacement(
            employee_on_leave_id=employee_id,
            replacement_employee_id=replacement_employee_id,
            date=date
        )
        db.session.add(new_replacement)
        approved_dates.append(date_str)

    db.session.commit()

    response = {
        'approved': approved_dates,
        'declined': declined_dates
    }
    return jsonify(response)

@app.route('/get_leaves')
def get_leaves():
    leaves = Leave.query.all()
    leave_list = [{'title': leave.employee.name, 'start': leave.date.strftime('%Y-%m-%d')} for leave in leaves]
    return jsonify(leave_list)

@app.route('/get_replacements')
def get_replacements():
    replacements = Replacement.query.all()
    data = []
    for r in replacements:
        employee_on_leave = Employee.query.get(r.employee_on_leave_id)
        replacement_employee = Employee.query.get(r.replacement_employee_id)
        data.append({
            'employee_on_leave': employee_on_leave.name,
            'replacement_employee': replacement_employee.name,
            'date': r.date.strftime('%Y-%m-%d')
        })
    return jsonify(data)

@app.route('/leave_schedule')
def leave_schedule():
    leaves = Leave.query.order_by(Leave.date).all()
    schedule = []

    for leave in leaves:
        employee = Employee.query.get(leave.employee_id)
        replacement = Replacement.query.filter_by(employee_on_leave_id=employee.id, date=leave.date).first()
        if replacement:
            replacement_employee = Employee.query.get(replacement.replacement_employee_id)
            replacement_name = replacement_employee.name
        else:
            replacement_name = 'No Replacement'
        schedule.append({
            'employee_name': employee.name,
            'date': leave.date.strftime('%Y-%m-%d'),
            'replacement_name': replacement_name
        })

    return render_template('leave_schedule.html', schedule=schedule)

# Admin Authentication Routes
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == app.config['ADMIN_USERNAME'] and password == app.config['ADMIN_PASSWORD']:
            session['is_admin'] = True
            return redirect(url_for('index'))
        else:
            error = 'Invalid credentials'
            return render_template('admin_login.html', error=error)
    return render_template('admin_login.html')

@app.route('/admin_logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))

# Admin Routes for Editing Employees
@app.route('/edit_employees')
def edit_employees():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    employees = Employee.query.all()
    return render_template('edit_employees.html', employees=employees)

@app.route('/edit_employee/<int:employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    employee = Employee.query.get_or_404(employee_id)
    if request.method == 'POST':
        new_name = request.form['name']
        if new_name:
            employee.name = new_name
            db.session.commit()
            return redirect(url_for('edit_employees'))
    return render_template('edit_employee.html', employee=employee)

@app.route('/delete_employee/<int:employee_id>', methods=['POST'])
def delete_employee(employee_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    employee = Employee.query.get_or_404(employee_id)
    # Delete associated leaves and replacements
    Leave.query.filter_by(employee_id=employee_id).delete()
    Replacement.query.filter_by(employee_on_leave_id=employee_id).delete()
    Replacement.query.filter_by(replacement_employee_id=employee_id).delete()
    db.session.delete(employee)
    db.session.commit()
    return redirect(url_for('edit_employees'))

# Admin Routes for Editing Leaves
@app.route('/edit_leaves')
def edit_leaves():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    leaves = Leave.query.order_by(Leave.date).all()
    schedule = []

    for leave in leaves:
        employee = Employee.query.get(leave.employee_id)
        replacement = Replacement.query.filter_by(employee_on_leave_id=employee.id, date=leave.date).first()
        if replacement:
            replacement_employee = Employee.query.get(replacement.replacement_employee_id)
            replacement_name = replacement_employee.name
        else:
            replacement_name = 'No Replacement'
        schedule.append({
            'leave_id': leave.id,
            'employee_name': employee.name,
            'date': leave.date.strftime('%Y-%m-%d'),
            'replacement_name': replacement_name
        })

    return render_template('edit_leaves.html', schedule=schedule)

@app.route('/edit_leave/<int:leave_id>', methods=['GET', 'POST'])
def edit_leave(leave_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    leave = Leave.query.get_or_404(leave_id)
    employee = Employee.query.get(leave.employee_id)
    if request.method == 'POST':
        new_date_str = request.form['date']
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
        # Update leave date
        old_date = leave.date
        leave.date = new_date
        # Update replacement date
        replacement = Replacement.query.filter_by(employee_on_leave_id=employee.id, date=old_date).first()
        if replacement:
            replacement.date = new_date
        db.session.commit()
        return redirect(url_for('edit_leaves'))
    return render_template('edit_leave.html', leave=leave, employee=employee)

@app.route('/delete_leave/<int:leave_id>', methods=['POST'])
def delete_leave(leave_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    leave = Leave.query.get_or_404(leave_id)
    # Delete associated replacement
    Replacement.query.filter_by(employee_on_leave_id=leave.employee_id, date=leave.date).delete()
    db.session.delete(leave)
    db.session.commit()
    return redirect(url_for('edit_leaves'))

if __name__ == '__main__':
    app.run(debug=True)

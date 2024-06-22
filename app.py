from datetime import datetime, timedelta
from flask import Flask, jsonify, request, session
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import logging

app = Flask(__name__)
CORS(app)
app.secret_key = 'medicine-inventory'
client = MongoClient('mongodb://localhost:27017')
db = client['medicine_inventory']
users = db['users']

users.create_index('username', unique=True)
logging.basicConfig(level=logging.DEBUG)


@app.route('/', methods=['GET', 'POST'])
def home():
    return jsonify("Welcome to MedAPI")


@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role')

    if users.find_one({'username': username}):
        return jsonify({"error": "Username already exists"}), 400

    hashed_password = generate_password_hash(password)

    user = {
        'username': username,
        'password': hashed_password,
        'role': role
    }
    users.insert_one(user)

    return jsonify({"message": "User registers successfully"}), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user = users.find_one({'username': username})
    if not user or not check_password_hash(user['password'], password):
        return jsonify({"error": "Invalid username or password"}), 401

    session['user'] = user
    return jsonify({"message": "Login successful", "user": user})


@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({"message": "Logout successful"})


@app.route('/stock', methods=['GET', 'POST'])
def stock():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if session['user']['role'] != 'admin' and session['user']['role'] != 'user':
        return jsonify({"error": "Unauthorized"}), 403

    if request.method == 'GET':
        stockcomplete = list(db['stock'].find({}, {'_id': 0}))
        return jsonify(stockcomplete)
    elif request.method == 'POST':
        data = request.json
        db['stock'].insert_one(data)
        return jsonify({"message": "Stock added successfully!"})


@app.route('/billing', methods=['POST'])
def billing():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if session['user']['role'] != 'admin' and session['user']['role'] != 'user':
        return jsonify({"error": "Unauthorized"}), 403
    data = request.json
    patient_id = data.get('patient_id')
    medicines = data.get('medicines')

    if not (patient_id and medicines):
        return jsonify({"error": "Missing required data: patient_id and medicines are required."}), 400

    bill_items = []
    total_amount = 0

    for item in medicines:
        medicine_name = item.get('medicine_name')
        qty_sold = item.get('qty_sold')

        if not (medicine_name and qty_sold):
            return jsonify(
                {"error": "Missing required data in medicines: medicine_name and qty_sold are required."}), 400

        try:
            qty_sold = int(qty_sold)
        except ValueError:
            return jsonify({"error": f"Invalid quantity sold for {medicine_name}. It must be an integer."}), 400

        medicine = db['stock'].find_one({"product_name": medicine_name})
        if not medicine:
            return jsonify({"error": f"Medicine '{medicine_name}' not found in stock."}), 400
        if int(medicine.get('qty', 0)) < qty_sold:
            return jsonify({"error": f"Not enough stock for {medicine_name}"}), 400

        new_qty = int(medicine['qty']) - qty_sold
        db['stock'].update_one({"product_name": medicine_name}, {"$set": {"qty": new_qty}})

        bill_amount = int(medicine['mrp']) * qty_sold
        total_amount += bill_amount

        bill_items.append({
            "medicine_name": medicine_name,
            "qty_sold": qty_sold,
            "qty_remaining": new_qty,
            "mrp": int(medicine['mrp']),
            "bill_amount": bill_amount
        })

    transaction = {
        "patient_id": patient_id,
        "medicines": bill_items,
        "total_amount": total_amount,
        "transaction_time": datetime.utcnow()
    }
    db['transactions'].insert_one(transaction)

    return jsonify({"message": "Bill generated successfully!", "total_amount": total_amount, "bill_items": bill_items})


@app.route('/sales', methods=['GET'])
def sales():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if session['user']['role'] != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if not start_date or not end_date:
            return jsonify({"message": "Start date and end date are required"}), 400

        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

        sales = list(db['transactions'].find({
            "transaction_time": {"$gte": start_date, "$lt": end_date}
        }, {'_id': 0}))

        total_earnings = sum(float(sale['total_amount']) for sale in sales)

        return jsonify({"sales": sales, "total_earnings": total_earnings})
    except Exception as e:
        app.logger.error(f"Error fetching sales data: {e}")
        return jsonify({"message": "An error occurred", "error": str(e)}), 500


@app.route('/medicines', methods=['GET'])
def get_medicines():
    try:
        medicines = db['stock'].distinct("product_name")
        return jsonify({"medicines": medicines})
    except Exception as e:
        app.logger.error(f"Error fetching medicines: {e}")
        return jsonify({"message": "An error occurred while fetching medicines", "error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)

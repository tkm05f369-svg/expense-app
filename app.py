from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import json
import os
import sqlite3
from datetime import date
import openai
import base64
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", "dummy"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        db = sqlite3.connect("expenses.db")
        db.row_factory = sqlite3.Row
        return db

def init_db():
    db = get_db()
    cursor = db.cursor()
    if DATABASE_URL:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                item TEXT NOT NULL,
                category TEXT,
                amount INTEGER NOT NULL
            )
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                item TEXT NOT NULL,
                category TEXT,
                amount INTEGER NOT NULL
            )
        """)
    db.commit()
    db.close()

init_db()

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = %s" if DATABASE_URL else "SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    db.close()
    if user:
        return User(user[0], user[1])
    return None

@app.route("/")
@login_required
def index():
    return render_template("index.html", username=current_user.username)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        data = request.get_json()
        username = data["username"]
        password = generate_password_hash(data["password"])
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)" if DATABASE_URL else "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            db.commit()
            db.close()
            return jsonify({"message": "登録完了"})
        except Exception:
            db.close()
            return jsonify({"error": "このユーザー名は既に使われています"}), 400
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.get_json()
        username = data["username"]
        password = data["password"]
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE username = %s" if DATABASE_URL else "SELECT * FROM users WHERE username = ?",
            (username,)
        )
        user = cursor.fetchone()
        db.close()
        if user and check_password_hash(user[2], password):
            login_user(User(user[0], user[1]))
            return jsonify({"message": "ログイン成功"})
        return jsonify({"error": "ユーザー名またはパスワードが間違っています"}), 401
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/expenses", methods=["GET"])
@login_required
def get_expenses():
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM expenses WHERE user_id = %s ORDER BY date DESC" if DATABASE_URL else "SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC",
        (current_user.id,)
    )
    rows = cursor.fetchall()
    db.close()
    expenses = [{"id": r[0], "user_id": r[1], "date": r[2], "item": r[3], "category": r[4], "amount": r[5]} for r in rows]
    return jsonify(expenses)

@app.route("/expenses", methods=["POST"])
@login_required
def add_expense():
    data = request.get_json()
    item = data["item"]
    amount = data["amount"]
    today = str(date.today())
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO expenses (user_id, date, item, category, amount) VALUES (%s, %s, %s, %s, %s)" if DATABASE_URL else "INSERT INTO expenses (user_id, date, item, category, amount) VALUES (?, ?, ?, ?, ?)",
        (current_user.id, today, item, "未分類", amount)
    )
    db.commit()
    db.close()
    return jsonify({"message": "追加しました"})

@app.route("/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "DELETE FROM expenses WHERE id = %s AND user_id = %s" if DATABASE_URL else "DELETE FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, current_user.id)
    )
    db.commit()
    db.close()
    return jsonify({"message": "削除しました"})

@app.route("/report")
@login_required
def report():
    db = get_db()
    cursor = db.cursor()
    if DATABASE_URL:
        cursor.execute("""
            SELECT 
                TO_CHAR(date::date, 'YYYY-MM') as month,
                category,
                SUM(amount) as total
            FROM expenses 
            WHERE user_id = %s
            GROUP BY month, category
            ORDER BY month DESC
        """, (current_user.id,))
    else:
        cursor.execute("""
            SELECT 
                strftime('%Y-%m', date) as month,
                category,
                SUM(amount) as total
            FROM expenses 
            WHERE user_id = ?
            GROUP BY month, category
            ORDER BY month DESC
        """, (current_user.id,))
    rows = cursor.fetchall()
    db.close()
    return jsonify([{"month": r[0], "category": r[1], "total": r[2]} for r in rows])

@app.route("/receipt", methods=["POST"])
@login_required
def read_receipt():
    file = request.files["receipt"]
    image_data = base64.b64encode(file.read()).decode("utf-8")
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_data}"
                        }
                    },
                    {
                        "type": "text",
                        "text": "このレシートから以下を日本語で抽出してください。JSON形式のみ返してください。前後に余計なテキストは不要です。勘定科目は日本の確定申告で使われる科目（交通費、接待交際費、通信費、消耗品費、外注費、地代家賃、水道光熱費、広告宣伝費、その他）から最適なものを選んでください。{\"店名\": \"\", \"日付\": \"\", \"合計金額\": 0, \"勘定科目\": \"\", \"品目\": [{\"名前\": \"\", \"金額\": 0}]}"
                    }
                ]
            }
        ],
        max_tokens=1000
    )
    
    content = response.choices[0].message.content
    content = content.replace("```json", "").replace("```", "").strip()
    result = json.loads(content)
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO expenses (user_id, date, item, category, amount) VALUES (%s, %s, %s, %s, %s)" if DATABASE_URL else "INSERT INTO expenses (user_id, date, item, category, amount) VALUES (?, ?, ?, ?, ?)",
        (current_user.id, result.get("日付", str(date.today())), result.get("店名", "不明"), result.get("勘定科目", "未分類"), result.get("合計金額", 0))
    )
    db.commit()
    db.close()
    
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
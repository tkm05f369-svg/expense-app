from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
import json
import os
import sqlite3
from datetime import date
import openai
import base64
import stripe
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", "dummy"))
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("GMAIL_ADDRESS")
app.config["MAIL_PASSWORD"] = os.getenv("GMAIL_APP_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("GMAIL_ADDRESS")

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)

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
                password TEXT NOT NULL,
                is_premium BOOLEAN DEFAULT FALSE,
                stripe_customer_id TEXT,
                email TEXT
            )
        """)
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
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
                password TEXT NOT NULL,
                is_premium INTEGER DEFAULT 0,
                stripe_customer_id TEXT,
                email TEXT
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
    def __init__(self, id, username, is_premium=False):
        self.id = id
        self.username = username
        self.is_premium = is_premium

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = %s" if DATABASE_URL else "SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    db.close()
    if user:
        return User(user[0], user[1], bool(user[3]))
    return None

@app.route("/")
@login_required
def index():
    return render_template("index.html", username=current_user.username, is_premium=current_user.is_premium, stripe_public_key=STRIPE_PUBLIC_KEY)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        data = request.get_json()
        username = data["username"]
        email = data.get("email", "")
        password = generate_password_hash(data["password"])
        db = get_db()
        cursor = db.cursor()
        try:
            if DATABASE_URL:
                cursor.execute("INSERT INTO users (username, password, email) VALUES (%s, %s, %s)", (username, password, email))
            else:
                cursor.execute("INSERT INTO users (username, password, email) VALUES (?, ?, ?)", (username, password, email))
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
            login_user(User(user[0], user[1], bool(user[3])))
            return jsonify({"message": "ログイン成功"})
        return jsonify({"error": "ユーザー名またはパスワードが間違っています"}), 401
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        data = request.get_json()
        email = data["email"]
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE email = %s" if DATABASE_URL else "SELECT * FROM users WHERE email = ?",
            (email,)
        )
        user = cursor.fetchone()
        db.close()
        if user:
            token = serializer.dumps(email, salt="password-reset")
            reset_url = request.host_url + f"reset-password/{token}"
            msg = Message("パスワードリセット", recipients=[email])
            msg.body = f"以下のURLからパスワードをリセットしてください。\n\n{reset_url}\n\n有効期限は1時間です。"
            mail.send(msg)
        return jsonify({"message": "メールを送信しました（登録済みの場合）"})
    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="password-reset", max_age=3600)
    except Exception:
        return "リンクが無効または期限切れです", 400
    if request.method == "POST":
        data = request.get_json()
        new_password = generate_password_hash(data["password"])
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE users SET password = %s WHERE email = %s" if DATABASE_URL else "UPDATE users SET password = ? WHERE email = ?",
            (new_password, email)
        )
        db.commit()
        db.close()
        return jsonify({"message": "パスワードを変更しました"})
    return render_template("reset_password.html", token=token)

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

@app.route("/expenses/<int:expense_id>", methods=["PUT"])
@login_required
def update_expense(expense_id):
    data = request.get_json()
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE expenses SET date = %s, item = %s, category = %s, amount = %s WHERE id = %s AND user_id = %s" if DATABASE_URL else "UPDATE expenses SET date = ?, item = ?, category = ?, amount = ? WHERE id = ? AND user_id = ?",
        (data["date"], data["item"], data["category"], data["amount"], expense_id, current_user.id)
    )
    db.commit()
    db.close()
    return jsonify({"message": "更新しました"})

@app.route("/report")
@login_required
def report():
    db = get_db()
    cursor = db.cursor()
    if DATABASE_URL:
        cursor.execute("""
            SELECT LEFT(date, 7) as month, category, SUM(amount) as total
            FROM expenses WHERE user_id = %s
            GROUP BY month, category ORDER BY month DESC
        """, (current_user.id,))
    else:
        cursor.execute("""
            SELECT strftime('%Y-%m', date) as month, category, SUM(amount) as total
            FROM expenses WHERE user_id = ?
            GROUP BY month, category ORDER BY month DESC
        """, (current_user.id,))
    rows = cursor.fetchall()
    db.close()
    return jsonify([{"month": r[0], "category": r[1], "total": r[2]} for r in rows])

@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        mode="subscription",
        success_url=request.host_url + "payment-success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=request.host_url,
        client_reference_id=str(current_user.id)
    )
    return jsonify({"url": session.url})

@app.route("/payment-success")
@login_required
def payment_success():
    session_id = request.args.get("session_id")
    if session_id:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        user_id = checkout_session.client_reference_id
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE users SET is_premium = %s WHERE id = %s" if DATABASE_URL else "UPDATE users SET is_premium = 1 WHERE id = ?",
            (True, user_id) if DATABASE_URL else (user_id,)
        )
        db.commit()
        db.close()
    return redirect(url_for("index"))

@app.route("/receipt", methods=["POST"])
@login_required
def read_receipt():
    file = request.files["receipt"]
    image_data = base64.b64encode(file.read()).decode("utf-8")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                {"type": "text", "text": "このレシートから以下を日本語で抽出してください。JSON形式のみ返してください。前後に余計なテキストは不要です。日付はYYYY-MM-DD形式で返してください。勘定科目は日本の確定申告で使われる科目（交通費、接待交際費、通信費、消耗品費、外注費、地代家賃、水道光熱費、広告宣伝費、その他）から最適なものを選んでください。{\"店名\": \"\", \"日付\": \"\", \"合計金額\": 0, \"勘定科目\": \"\", \"品目\": [{\"名前\": \"\", \"金額\": 0}]}"}
            ]
        }],
        max_tokens=1000
    )
    content = response.choices[0].message.content
    content = content.replace("```json", "").replace("```", "").strip()
    result = json.loads(content)
    receipt_date = result.get("日付", str(date.today()))
    if "年" in receipt_date:
        receipt_date = receipt_date.replace("年", "-").replace("月", "-").replace("日", "")
        parts = receipt_date.split("-")
        receipt_date = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO expenses (user_id, date, item, category, amount) VALUES (%s, %s, %s, %s, %s)" if DATABASE_URL else "INSERT INTO expenses (user_id, date, item, category, amount) VALUES (?, ?, ?, ?, ?)",
        (current_user.id, receipt_date, result.get("店名", "不明"), result.get("勘定科目", "未分類"), result.get("合計金額", 0))
    )
    db.commit()
    db.close()
    return jsonify(result)

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html", email=os.getenv("GMAIL_ADDRESS"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
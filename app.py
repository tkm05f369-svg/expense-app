from flask import Flask, request, jsonify, render_template
import json
import os
from datetime import date
import openai
import base64
from dotenv import load_dotenv

load_dotenv()
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)
filename = "expenses.json"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/expenses", methods=["GET"])
def get_expenses():
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            expenses = json.load(f)
    else:
        expenses = []
    return jsonify(expenses)

@app.route("/expenses", methods=["POST"])
def add_expense():
    data = request.get_json()
    item = data["item"]
    amount = data["amount"]
    today = str(date.today())
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            expenses = json.load(f)
    else:
        expenses = []
    expenses.append({"date": today, "item": item, "amount": amount})
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(expenses, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "追加しました", "expense": {"date": today, "item": item, "amount": amount}})

@app.route("/receipt", methods=["POST"])
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
    
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            expenses = json.load(f)
    else:
        expenses = []
    
    expenses.append({
        "date": result.get("日付", str(date.today())),
        "item": result.get("店名", "不明"),
        "category": result.get("勘定科目", "未分類"),
        "amount": result.get("合計金額", 0)
    })
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(expenses, f, ensure_ascii=False, indent=2)
    
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
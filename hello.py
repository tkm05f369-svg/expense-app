import json
import os
from datetime import date

filename = "expenses.json"

if os.path.exists(filename):
    with open(filename, "r", encoding="utf-8") as f:
        expenses = json.load(f)
else:
    expenses = []

while True:
    item = input("経費の名前（終わりはEnterだけ押す）: ")
    if item == "":
        break
    amount = input("金額: ")
    amount = int(amount)
    today = str(date.today())
    expenses.append({"date": today, "item": item, "amount": amount})

with open(filename, "w", encoding="utf-8") as f:
    json.dump(expenses, f, ensure_ascii=False, indent=2)

print("\n--- 経費一覧（累計）---")
total = 0
for e in expenses:
    print(e["date"] + " | " + e["item"] + ": " + str(e["amount"]) + "円")
    total += e["amount"]

print("合計: " + str(total) + "円")

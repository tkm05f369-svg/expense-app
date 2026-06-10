import openai
import base64
import os
from dotenv import load_dotenv

load_dotenv()
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def read_receipt(image_path):
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")
    
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
                        "text": "このレシートから以下を日本語で抽出してください。JSON形式で返してください。{\"店名\": \"\", \"日付\": \"\", \"合計金額\": 0, \"品目\": [{\"名前\": \"\", \"金額\": 0}]}"
                    }
                ]
            }
        ],
        max_tokens=1000
    )
    
    return response.choices[0].message.content

image_path = "test_receipt.jpg"
result = read_receipt(image_path)
print(result)
from dotenv import load_dotenv
load_dotenv()
from sarvamai import SarvamAI
import os

client = SarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))

response = client.chat.completions(
    model="sarvam-105b",#sarvam-105b
    messages=[
        {"role": "system", "content": "You are an expert resume matcher and ATS optimizer..."},
        {"role": "user", "content": f"Who are you? What can you do for me?"}
    ],
)
print(response.choices[0].message.content)

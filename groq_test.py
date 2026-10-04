import os
import json
from dotenv import load_dotenv
from groq import Groq

# .env থেকে API key লোড করো
load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

# চেক করো key আছে কি না
if not api_key:
    print("❌ GROQ_API_KEY .env ফাইলে নেই!")
    exit(1)

if not api_key.startswith("gsk_"):
    print("⚠️  API key gsk_ দিয়ে শুরু হয় না — সঠিক কি না দেখুন")

print(f"✅ API Key loaded: {api_key[:12]}...")

# Groq client তৈরি করো
client = Groq(api_key=api_key)

# টেস্ট prompt — BTC-র জন্য সিগন্যাল
prompt = """You are a professional crypto trading analyst.

Analyze this market data and give a signal:
- Symbol: BTCUSDT
- Price: $62000
- 24h Change: +2.3%
- RSI (15m): 58
- Funding Rate: 0.01%
- Trend: Bullish

Respond ONLY with valid JSON, no other text:
{"bias": "long", "confidence": 72, "reason": "short reason here"}
"""

print("\n🔄 Groq-কে পাঠানো হচ্ছে...\n")

try:
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=200,
    )

    raw = response.choices[0].message.content.strip()
    print("📩 AI Raw Output:")
    print(raw)

    # JSON parse ট্রাই করো
    print("\n🔍 JSON parse:")
    try:
        parsed = json.loads(raw)
        print(f"  Bias:       {parsed.get('bias')}")
        print(f"  Confidence: {parsed.get('confidence')}")
        print(f"  Reason:     {parsed.get('reason')}")
        print("\n✅ ফেজ ১ সফল!")
    except json.JSONDecodeError:
        print("⚠️  AI JSON দেয়নি, টেক্সট দিয়েছে। Prompt ঠিক করতে হবে।")

except Exception as e:
    print(f"❌ Error: {e}")

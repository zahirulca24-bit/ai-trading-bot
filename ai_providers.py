import os
import json
from dotenv import load_dotenv

load_dotenv()


def build_prompt(symbol, data):
    return f"""You are a professional crypto intraday trader.
Analyze this 15-minute data and give ONE trading signal.

Symbol: {symbol}
Price: {data['price']}
24h Change: {data['change_24h']}%
Funding Rate: {data['funding_rate']}%
RSI (15m): {data['rsi_15m']}

Rules:
- Confidence below 60 -> bias must be "neutral"
- RSI > 70 -> consider short
- RSI < 30 -> consider long

Output a single JSON object on ONE line. No markdown.
Format: {{"bias": "long", "confidence": 72, "reason": "short text"}}
"""


def extract_json(text):
    if not text:
        raise ValueError("empty")
    text = text.strip()
    if "```" in text:
        for p in text.split("```"):
            p = p.replace("json", "").strip()
            if p.startswith("{"):
                text = p
                break
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except Exception:
                        break
    raise ValueError(f"no json in: {text[:60]}")


def normalize(parsed):
    bias = str(parsed.get("bias", "neutral")).lower()
    if bias not in ("long", "short", "neutral"):
        bias = "neutral"
    try:
        confidence = int(parsed.get("confidence", 0))
    except Exception:
        confidence = 0
    reason = str(parsed.get("reason", ""))[:120]
    return {"bias": bias, "confidence": confidence, "reason": reason}


def ask_groq(symbol, data):
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        for m in ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]:
            try:
                r = client.chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": "Reply ONLY with single-line JSON."},
                        {"role": "user", "content": build_prompt(symbol, data)},
                    ],
                    temperature=0.1,
                    max_tokens=200,
                )
                return normalize(extract_json(r.choices[0].message.content))
            except Exception:
                continue
    except Exception as e:
        print(f"  groq error: {str(e)[:50]}")
    return None


def ask_gemini(symbol, data):
    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=build_prompt(symbol, data),
        )
        return normalize(extract_json(response.text))
    except Exception as e:
        print(f"  gemini error: {str(e)[:70]}")
        return None


def get_all_signals(symbol, data):
    return {
        "groq": ask_groq(symbol, data),
        "gemini": ask_gemini(symbol, data),
    }


if __name__ == "__main__":
    print("Testing Groq + Gemini...\n")
    test_data = {
        "price": 85000.0,
        "change_24h": 2.3,
        "funding_rate": 0.01,
        "rsi_15m": 58.5,
    }
    results = get_all_signals("BTCUSDT", test_data)
    for name, r in results.items():
        print(f"{name}: {r}")

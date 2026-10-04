def consensus(signals):
    """
    signals: {"groq": {...}, "gemini": {...}}
    return:  {"bias": ..., "confidence": ..., "reason": ..., "votes": {...}}

    Rule: উভয় প্রোভাইডারের সিগন্যাল লাগবে।
    একটি ফেল করলে বা মত আলাদা হলে -> neutral (skip)
    """
    valid = {k: v for k, v in signals.items() if v is not None}

    if len(valid) < 2:
        return {
            "bias": "neutral",
            "confidence": 0,
            "reason": f"need 2 providers, got {len(valid)}",
            "votes": {},
            "providers": {k: v["bias"] for k, v in valid.items()} if valid else {},
        }

    biases = [v["bias"] for v in valid.values()]
    confidences = [v["confidence"] for v in valid.values()]
    total = len(biases)

    votes = {
        "long": biases.count("long"),
        "short": biases.count("short"),
        "neutral": biases.count("neutral"),
    }

    providers_map = {k: v["bias"] for k, v in valid.items()}
    reason_text = " | ".join(f"{k}:{v['reason'][:30]}" for k, v in valid.items())[:150]

    if votes["long"] == total:
        return {
            "bias": "long",
            "confidence": int(sum(confidences) / total),
            "reason": "unanimous long: " + reason_text,
            "votes": votes,
            "providers": providers_map,
        }

    if votes["short"] == total:
        return {
            "bias": "short",
            "confidence": int(sum(confidences) / total),
            "reason": "unanimous short: " + reason_text,
            "votes": votes,
            "providers": providers_map,
        }

    if votes["neutral"] == total:
        return {
            "bias": "neutral",
            "confidence": int(sum(confidences) / total),
            "reason": "all neutral: " + reason_text,
            "votes": votes,
            "providers": providers_map,
        }

    return {
        "bias": "neutral",
        "confidence": 0,
        "reason": f"disagreement: {votes}",
        "votes": votes,
        "providers": providers_map,
    }


if __name__ == "__main__":
    print("Consensus Test (strict)\n")

    print("Case 1 - both long:")
    print(consensus({
        "groq": {"bias": "long", "confidence": 70, "reason": "momentum up"},
        "gemini": {"bias": "long", "confidence": 65, "reason": "RSI rising"},
    }))
    print()

    print("Case 2 - disagreement:")
    print(consensus({
        "groq": {"bias": "long", "confidence": 70, "reason": "momentum up"},
        "gemini": {"bias": "short", "confidence": 65, "reason": "overbought"},
    }))
    print()

    print("Case 4 - one provider down (should skip now):")
    print(consensus({
        "groq": {"bias": "long", "confidence": 70, "reason": "momentum up"},
        "gemini": None,
    }))

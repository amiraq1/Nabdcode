def is_refusal(text: str) -> bool:
    if not text:
        return False
    patterns = ["لا أستطيع", "I cannot", "I'm unable", "لا يمكنني"]
    return any(p in text for p in patterns)

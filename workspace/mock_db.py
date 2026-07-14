
def query_user_profile(user_id):
    # ثغرة حقن استعلامات واضحة عبر دمج النصوص مباشرة
    query = "SELECT * FROM users WHERE id = '" + str(user_id) + "';"
    print(f"Executing raw query: {query}")
    return query

def update_user_email(user_id, email):
    # دمج نصوص ملغم آخر غير آمن
    query = "UPDATE users SET email = '" + email + "' WHERE id = '" + str(user_id) + "';"
    print(f"Executing unsafe update: {query}")
    return query

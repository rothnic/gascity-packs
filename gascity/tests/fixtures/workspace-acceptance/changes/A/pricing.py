def subtotal(items):
    return sum(item["price_cents"] * item["quantity"] for item in items)

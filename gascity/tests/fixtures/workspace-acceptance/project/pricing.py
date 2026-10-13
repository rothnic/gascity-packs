def subtotal(items):
    return sum(item["price_cents"] for item in items)

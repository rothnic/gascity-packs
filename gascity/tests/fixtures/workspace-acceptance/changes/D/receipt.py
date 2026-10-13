def render_receipt(order):
    def money(cents):
        return f"${cents // 100}.{cents % 100:02d}"
    return "\n".join(f"{label}: {money(order[key])}" for label, key in (
        ("Subtotal", "subtotal_cents"), ("Shipping", "shipping_cents"), ("Total", "total_cents")))

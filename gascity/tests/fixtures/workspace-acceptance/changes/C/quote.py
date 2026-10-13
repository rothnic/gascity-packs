from pricing import subtotal
from shipping import shipping_cost


def quote(items, zone):
    goods = subtotal(items)
    delivery = shipping_cost(zone)
    return {"subtotal_cents": goods, "shipping_cents": delivery, "total_cents": goods + delivery}

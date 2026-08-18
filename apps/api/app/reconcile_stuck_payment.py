"""One-off: manually completes a wallet recharge whose /verify call crashed after Razorpay had
already captured the payment (the erpnext_sync_status NOT NULL bug, fixed separately) -- reuses
the exact same credit/invoice logic verify_payment itself calls, skipping only the client-supplied
signature check (the browser-side razorpay_signature was never persisted anywhere once that request
failed) in favor of a direct server-to-server fetch of the payment from Razorpay, which is at least
as trustworthy. Delete this file once the one stuck order is resolved -- not meant to be reusable
tooling, this exists to unblock the specific incident.

Run inside the api container: python -m app.reconcile_stuck_payment <razorpay_order_id>
"""
import sys

from sqlalchemy import select

from .database import SessionLocal
from .invoicing import create_draft_invoice, issue_invoice
from .models import Entity, PaymentOrder, User
from .services import GST_RATE, credit_wallet, enforce_topup_integrity, expected_order_paise, get_platform_razorpay_keys

import razorpay


def main(provider_order_id: str) -> None:
    db = SessionLocal()
    try:
        order = db.scalar(select(PaymentOrder).where(PaymentOrder.provider_order_id == provider_order_id))
        if not order:
            print(f"No PaymentOrder found for {provider_order_id}")
            return
        if order.status != "created":
            print(f"Order is already {order.status!r} -- nothing to do")
            return

        key_id, key_secret = get_platform_razorpay_keys(db)
        client = razorpay.Client(auth=(key_id, key_secret))

        payment_id = input("Razorpay payment_id (pay_...): ").strip()
        razorpay_payment = client.payment.fetch(payment_id)
        expected_paise = expected_order_paise(order)
        if razorpay_payment.get("status") != "captured" or razorpay_payment.get("amount") != expected_paise:
            print(f"Razorpay does not confirm this payment: status={razorpay_payment.get('status')} amount={razorpay_payment.get('amount')} expected={expected_paise}")
            return

        entity = db.get(Entity, order.entity_id)
        user = db.get(User, order.user_id) if order.user_id else None
        if not user:
            print("Order has no linked user_id -- reconcile manually.")
            return

        if not order.price_per_sms:
            print("This order has no snapshotted price_per_sms -- reconcile manually, this script doesn't handle that legacy case.")
            return
        credits = float(order.amount) / float(order.price_per_sms)

        wallet = credit_wallet(db, entity.id, credits, transaction_type="recharge_razorpay", reference=payment_id)
        order.status = "paid"
        order.credits_applied = credits
        gst_amount = round(float(order.amount) * GST_RATE, 2)
        price_per_sms = float(order.price_per_sms) if order.price_per_sms else (float(order.amount) / credits if credits else None)
        invoice = create_draft_invoice(db, entity, type="wallet_recharge", base_amount=float(order.amount), gst_amount=gst_amount, reference=order.id, credits_purchased=round(credits, 2), price_per_sms=price_per_sms)
        issue_invoice(db, invoice)

        if enforce_topup_integrity(db, order, entity, user, credits):
            db.commit()
            print("Integrity check failed -- account placed on hold, review manually.")
            return

        db.commit()
        available = float(wallet.prepaid_balance) + max(0, float(wallet.credit_limit) - float(wallet.credit_used))
        print(f"Credited {credits:.2f} SMS credits. New available balance: {available:.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1])

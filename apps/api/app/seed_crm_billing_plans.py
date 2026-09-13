"""One-off seed for a real, differentiated CRM plan catalog. Per-plan feature gating
(BillingPlan.feature_flags, permissions.require_plan_feature[_by_path]) has existed since this
project's Addendum 4/12 work, but no admin had ever created named tiers with it -- every CRM plan
in production today was ad hoc and left feature_flags null (every feature unlocked). This creates
three real tiers (Starter/Growth/Pro) at monthly and quarterly periods each, so plans actually
differ in what they unlock, not just in seat count.

Feature split: Starter has none of CRM_GATEABLE_FEATURES (leads/deals/contacts/companies/tasks/
pipelines/reports stay unrestricted on every tier -- only the 5 gateable features below ever
restrict anything). Growth adds Quotes, Automation, and the Report Builder. Pro adds everything
Growth has plus Email and Tickets.

Safe to run more than once -- for any (channel, name, period) combination that already exists
(e.g. from an admin/QA-created plan sharing one of these names), this only patches feature_flags
to the intended split rather than skipping outright or overwriting price/user_limit -- a real
account may already have paying subscribers on that plan id (ChannelSubscription.plan_id), so the
row is never deleted/recreated, only its feature gating corrected in place.

Usage: python -m app.seed_crm_billing_plans
"""
from .database import SessionLocal
from .models import BillingPlan

PLANS = [
    {"name": "CRM Starter", "price": 999, "user_limit": 3, "feature_flags": []},
    {"name": "CRM Growth", "price": 2499, "user_limit": 10, "feature_flags": ["crm-quotes", "crm-automation", "crm-report-builder"]},
    {"name": "CRM Pro", "price": 4999, "user_limit": None, "feature_flags": ["crm-quotes", "crm-automation", "crm-report-builder", "crm-email", "tickets"]},
]
PERIODS = {"monthly": 1, "quarterly": 3}


def seed() -> None:
    db = SessionLocal()
    try:
        created = 0
        patched = 0
        for plan in PLANS:
            for period, months in PERIODS.items():
                existing = db.query(BillingPlan).filter(
                    BillingPlan.channel == "crm", BillingPlan.name == plan["name"], BillingPlan.period == period,
                ).first()
                if existing:
                    if existing.feature_flags != plan["feature_flags"]:
                        existing.feature_flags = plan["feature_flags"]
                        patched += 1
                        print(f"patched feature_flags: {plan['name']} / {period} (price/user_limit left as-is: real subscribers may reference this plan id)")
                    else:
                        print(f"skip (already correct): {plan['name']} / {period}")
                    continue
                # Quarterly at a ~10% discount vs. 3x the monthly price, same "real, not a clean
                # multiple" reasoning BillingPlan's own docstring gives for period being its own row.
                price = round(plan["price"] * months * (0.9 if months > 1 else 1), 2)
                db.add(BillingPlan(
                    channel="crm", name=plan["name"], period=period, price=price,
                    message_limit=None, user_limit=plan["user_limit"], active=True,
                    visible_to_customers=True, feature_flags=plan["feature_flags"],
                ))
                created += 1
                print(f"created: {plan['name']} / {period} / Rs.{price}")
        db.commit()
        print(f"done: {created} plan(s) created, {patched} plan(s) had feature_flags corrected")
    finally:
        db.close()


if __name__ == "__main__":
    seed()

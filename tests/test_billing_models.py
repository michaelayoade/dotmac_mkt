"""Tests for billing models."""

import uuid

from app.models.billing import (
    BillingScheme,
    Coupon,
    CouponDuration,
    Customer,
    Discount,
    Entitlement,
    EntitlementValueType,
    Invoice,
    InvoiceItem,
    InvoiceStatus,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentMethod,
    PaymentMethodType,
    Price,
    PriceType,
    Product,
    RecurringInterval,
    Subscription,
    SubscriptionItem,
    SubscriptionStatus,
    UsageAction,
    UsageRecord,
    WebhookEvent,
    WebhookEventStatus,
)


def test_create_product(db_session):
    product = Product(name="Pro Plan", description="Professional tier")
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    assert product.id is not None
    assert product.name == "Pro Plan"
    assert product.is_active is True


def test_create_price(db_session, billing_product):
    price = Price(
        product_id=billing_product.id,
        currency="usd",
        unit_amount=2999,
        type=PriceType.recurring,
        billing_scheme=BillingScheme.per_unit,
        recurring_interval=RecurringInterval.month,
        lookup_key=f"pro_monthly_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(price)
    db_session.commit()
    db_session.refresh(price)
    assert price.id is not None
    assert price.unit_amount == 2999
    assert price.type == PriceType.recurring
    assert price.recurring_interval == RecurringInterval.month


def test_create_customer(db_session):
    customer = Customer(
        name="Acme Inc",
        email="billing@acme.com",
        currency="usd",
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    assert customer.id is not None
    assert customer.balance == 0
    assert customer.is_active is True


def test_create_customer_with_person(db_session, person):
    customer = Customer(
        person_id=person.id,
        name="Personal",
        email="personal@example.com",
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    assert customer.person_id == person.id


def test_create_subscription(db_session, billing_customer):
    sub = Subscription(
        customer_id=billing_customer.id,
        status=SubscriptionStatus.active,
    )
    db_session.add(sub)
    db_session.commit()
    db_session.refresh(sub)
    assert sub.id is not None
    assert sub.status == SubscriptionStatus.active
    assert sub.cancel_at_period_end is False


def test_create_subscription_item(db_session, billing_subscription, billing_price):
    si = SubscriptionItem(
        subscription_id=billing_subscription.id,
        price_id=billing_price.id,
        quantity=5,
    )
    db_session.add(si)
    db_session.commit()
    db_session.refresh(si)
    assert si.quantity == 5


def test_create_invoice(db_session, billing_customer):
    inv = Invoice(
        customer_id=billing_customer.id,
        number=f"INV-{uuid.uuid4().hex[:8]}",
        status=InvoiceStatus.draft,
        currency="usd",
        subtotal=5000,
        tax=500,
        total=5500,
        amount_due=5500,
    )
    db_session.add(inv)
    db_session.commit()
    db_session.refresh(inv)
    assert inv.total == 5500
    assert inv.status == InvoiceStatus.draft


def test_create_invoice_item(db_session, billing_customer):
    inv = Invoice(
        customer_id=billing_customer.id,
        number=f"INV-{uuid.uuid4().hex[:8]}",
        status=InvoiceStatus.draft,
    )
    db_session.add(inv)
    db_session.commit()
    db_session.refresh(inv)

    line = InvoiceItem(
        invoice_id=inv.id,
        description="Pro Plan - Monthly",
        quantity=1,
        unit_amount=2999,
        amount=2999,
    )
    db_session.add(line)
    db_session.commit()
    db_session.refresh(line)
    assert line.amount == 2999


def test_create_payment_method(db_session, billing_customer):
    pm = PaymentMethod(
        customer_id=billing_customer.id,
        type=PaymentMethodType.card,
        details={"last4": "4242", "brand": "visa"},
        is_default=True,
    )
    db_session.add(pm)
    db_session.commit()
    db_session.refresh(pm)
    assert pm.details["last4"] == "4242"
    assert pm.is_default is True


def test_create_payment_intent(db_session, billing_customer):
    pi = PaymentIntent(
        customer_id=billing_customer.id,
        amount=5500,
        currency="usd",
        status=PaymentIntentStatus.requires_payment_method,
    )
    db_session.add(pi)
    db_session.commit()
    db_session.refresh(pi)
    assert pi.amount == 5500
    assert pi.status == PaymentIntentStatus.requires_payment_method


def test_create_usage_record(db_session, billing_subscription_item):
    ur = UsageRecord(
        subscription_item_id=billing_subscription_item.id,
        quantity=100,
        action=UsageAction.increment,
        idempotency_key=f"usage_{uuid.uuid4().hex}",
    )
    db_session.add(ur)
    db_session.commit()
    db_session.refresh(ur)
    assert ur.quantity == 100
    assert ur.action == UsageAction.increment


def test_create_coupon(db_session):
    coupon = Coupon(
        name="Summer Sale",
        code=f"SUMMER{uuid.uuid4().hex[:4].upper()}",
        percent_off=25,
        duration=CouponDuration.repeating,
        duration_in_months=3,
    )
    db_session.add(coupon)
    db_session.commit()
    db_session.refresh(coupon)
    assert coupon.percent_off == 25
    assert coupon.duration == CouponDuration.repeating
    assert coupon.times_redeemed == 0


def test_create_discount(db_session, billing_coupon, billing_customer):
    disc = Discount(
        coupon_id=billing_coupon.id,
        customer_id=billing_customer.id,
    )
    db_session.add(disc)
    db_session.commit()
    db_session.refresh(disc)
    assert disc.coupon_id == billing_coupon.id
    assert disc.customer_id == billing_customer.id


def test_create_entitlement(db_session, billing_product):
    ent = Entitlement(
        product_id=billing_product.id,
        feature_key="api_requests",
        value_type=EntitlementValueType.numeric,
        value_numeric=10000,
    )
    db_session.add(ent)
    db_session.commit()
    db_session.refresh(ent)
    assert ent.feature_key == "api_requests"
    assert ent.value_numeric == 10000


def test_create_entitlement_boolean(db_session, billing_product):
    ent = Entitlement(
        product_id=billing_product.id,
        feature_key="premium_support",
        value_type=EntitlementValueType.boolean,
        value_text="true",
    )
    db_session.add(ent)
    db_session.commit()
    db_session.refresh(ent)
    assert ent.value_type == EntitlementValueType.boolean


def test_create_webhook_event(db_session):
    event = WebhookEvent(
        provider="stripe",
        event_type="invoice.paid",
        event_id=f"evt_{uuid.uuid4().hex}",
        payload={"id": "inv_123"},
        status=WebhookEventStatus.pending,
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    assert event.provider == "stripe"
    assert event.status == WebhookEventStatus.pending


def test_product_price_relationship(db_session, billing_product, billing_price):
    db_session.refresh(billing_product)
    assert len(billing_product.prices) >= 1
    assert billing_price.product.id == billing_product.id


def test_customer_subscription_relationship(
    db_session, billing_customer, billing_subscription
):
    db_session.refresh(billing_customer)
    assert len(billing_customer.subscriptions) >= 1


def test_subscription_item_relationship(
    db_session, billing_subscription, billing_subscription_item
):
    db_session.refresh(billing_subscription)
    assert len(billing_subscription.items) >= 1

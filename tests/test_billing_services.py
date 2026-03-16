"""Tests for billing services."""

import uuid

import pytest
from fastapi import HTTPException

from app.schemas.billing import (
    CouponCreate,
    CouponUpdate,
    CustomerCreate,
    CustomerUpdate,
    DiscountCreate,
    EntitlementCreate,
    EntitlementUpdate,
    InvoiceCreate,
    InvoiceItemCreate,
    InvoiceItemUpdate,
    InvoiceUpdate,
    PaymentIntentCreate,
    PaymentIntentUpdate,
    PaymentMethodCreate,
    PaymentMethodUpdate,
    PriceCreate,
    PriceUpdate,
    ProductCreate,
    ProductUpdate,
    SubscriptionCreate,
    SubscriptionItemCreate,
    SubscriptionItemUpdate,
    SubscriptionUpdate,
    UsageRecordCreate,
    WebhookEventCreate,
    WebhookEventUpdate,
)
from app.services import billing as billing_service

# ── Products ─────────────────────────────────────────────


def test_create_product(db_session):
    product = billing_service.products.create(
        db_session, ProductCreate(name="Starter Plan", description="Basic tier")
    )
    assert product.name == "Starter Plan"
    assert product.is_active is True


def test_get_product(db_session):
    product = billing_service.products.create(
        db_session, ProductCreate(name="Get Test")
    )
    fetched = billing_service.products.get(db_session, str(product.id))
    assert fetched.id == product.id


def test_get_product_not_found(db_session):
    with pytest.raises(HTTPException) as exc_info:
        billing_service.products.get(db_session, str(uuid.uuid4()))
    assert exc_info.value.status_code == 404


def test_list_products(db_session):
    billing_service.products.create(db_session, ProductCreate(name="List P1"))
    billing_service.products.create(db_session, ProductCreate(name="List P2"))
    items, total = billing_service.products.list(
        db_session,
        is_active=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 2
    assert total >= 2


def test_update_product(db_session):
    product = billing_service.products.create(
        db_session, ProductCreate(name="Old Name")
    )
    updated = billing_service.products.update(
        db_session, str(product.id), ProductUpdate(name="New Name")
    )
    assert updated.name == "New Name"


def test_delete_product(db_session):
    product = billing_service.products.create(
        db_session, ProductCreate(name="To Delete")
    )
    billing_service.products.delete(db_session, str(product.id))
    fetched = billing_service.products.get(db_session, str(product.id))
    assert fetched.is_active is False


# ── Prices ───────────────────────────────────────────────


def test_create_price(db_session, billing_product):
    price = billing_service.prices.create(
        db_session,
        PriceCreate(
            product_id=billing_product.id,
            currency="usd",
            unit_amount=1999,
            type="recurring",
            recurring_interval="month",
        ),
    )
    assert price.unit_amount == 1999


def test_list_prices_filter_product(db_session, billing_product):
    billing_service.prices.create(
        db_session,
        PriceCreate(
            product_id=billing_product.id,
            currency="usd",
            unit_amount=999,
            type="one_time",
        ),
    )
    items, total = billing_service.prices.list(
        db_session,
        product_id=str(billing_product.id),
        type=None,
        currency=None,
        is_active=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1
    assert all(r.product_id == billing_product.id for r in items)


def test_update_price(db_session, billing_product):
    price = billing_service.prices.create(
        db_session,
        PriceCreate(
            product_id=billing_product.id,
            currency="usd",
            unit_amount=500,
            type="one_time",
        ),
    )
    updated = billing_service.prices.update(
        db_session, str(price.id), PriceUpdate(unit_amount=750)
    )
    assert updated.unit_amount == 750


# ── Customers ────────────────────────────────────────────


def test_create_customer(db_session):
    customer = billing_service.customers.create(
        db_session,
        CustomerCreate(name="Acme", email="acme@example.com"),
    )
    assert customer.name == "Acme"
    assert customer.currency == "usd"


def test_list_customers_filter_email(db_session):
    email = f"unique-{uuid.uuid4().hex[:8]}@example.com"
    billing_service.customers.create(
        db_session, CustomerCreate(name="Search Test", email=email)
    )
    items, total = billing_service.customers.list(
        db_session,
        person_id=None,
        email=email,
        is_active=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) == 1
    assert total == 1


def test_update_customer(db_session):
    customer = billing_service.customers.create(
        db_session,
        CustomerCreate(name="OldCo", email="old@example.com"),
    )
    updated = billing_service.customers.update(
        db_session, str(customer.id), CustomerUpdate(name="NewCo")
    )
    assert updated.name == "NewCo"


def test_delete_customer(db_session):
    customer = billing_service.customers.create(
        db_session,
        CustomerCreate(name="Del", email="del@example.com"),
    )
    billing_service.customers.delete(db_session, str(customer.id))
    fetched = billing_service.customers.get(db_session, str(customer.id))
    assert fetched.is_active is False


# ── Subscriptions ────────────────────────────────────────


def test_create_subscription(db_session, billing_customer):
    sub = billing_service.subscriptions.create(
        db_session,
        SubscriptionCreate(customer_id=billing_customer.id),
    )
    assert sub.status.value == "incomplete"


def test_list_subscriptions_filter_status(db_session, billing_customer):
    billing_service.subscriptions.create(
        db_session,
        SubscriptionCreate(customer_id=billing_customer.id, status="active"),
    )
    items, total = billing_service.subscriptions.list(
        db_session,
        customer_id=str(billing_customer.id),
        status="active",
        is_active=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1


def test_update_subscription(db_session, billing_customer):
    sub = billing_service.subscriptions.create(
        db_session,
        SubscriptionCreate(customer_id=billing_customer.id),
    )
    updated = billing_service.subscriptions.update(
        db_session,
        str(sub.id),
        SubscriptionUpdate(status="active"),
    )
    assert updated.status.value == "active"


# ── Subscription Items ───────────────────────────────────


def test_create_subscription_item(db_session, billing_subscription, billing_price):
    si = billing_service.subscription_items.create(
        db_session,
        SubscriptionItemCreate(
            subscription_id=billing_subscription.id,
            price_id=billing_price.id,
            quantity=3,
        ),
    )
    assert si.quantity == 3


def test_update_subscription_item(db_session, billing_subscription_item):
    updated = billing_service.subscription_items.update(
        db_session,
        str(billing_subscription_item.id),
        SubscriptionItemUpdate(quantity=10),
    )
    assert updated.quantity == 10


# ── Invoices ─────────────────────────────────────────────


def test_create_invoice(db_session, billing_customer):
    inv = billing_service.invoices.create(
        db_session,
        InvoiceCreate(
            customer_id=billing_customer.id,
            number=f"INV-{uuid.uuid4().hex[:8]}",
            subtotal=1000,
            total=1000,
            amount_due=1000,
        ),
    )
    assert inv.status.value == "draft"
    assert inv.total == 1000


def test_list_invoices_filter_status(db_session, billing_customer):
    billing_service.invoices.create(
        db_session,
        InvoiceCreate(
            customer_id=billing_customer.id,
            number=f"INV-{uuid.uuid4().hex[:8]}",
            status="open",
        ),
    )
    results = billing_service.invoices.list(
        db_session,
        customer_id=None,
        subscription_id=None,
        status="open",
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(results) >= 1


def test_update_invoice(db_session, billing_customer):
    inv = billing_service.invoices.create(
        db_session,
        InvoiceCreate(
            customer_id=billing_customer.id,
            number=f"INV-{uuid.uuid4().hex[:8]}",
        ),
    )
    updated = billing_service.invoices.update(
        db_session, str(inv.id), InvoiceUpdate(status="paid", amount_paid=1000)
    )
    assert updated.status.value == "paid"


# ── Invoice Items ────────────────────────────────────────


def test_create_invoice_item(db_session, billing_customer):
    inv = billing_service.invoices.create(
        db_session,
        InvoiceCreate(
            customer_id=billing_customer.id,
            number=f"INV-{uuid.uuid4().hex[:8]}",
        ),
    )
    line = billing_service.invoice_items.create(
        db_session,
        InvoiceItemCreate(
            invoice_id=inv.id,
            description="Line item",
            quantity=2,
            unit_amount=500,
            amount=1000,
        ),
    )
    assert line.amount == 1000


def test_update_invoice_item(db_session, billing_customer):
    inv = billing_service.invoices.create(
        db_session,
        InvoiceCreate(
            customer_id=billing_customer.id,
            number=f"INV-{uuid.uuid4().hex[:8]}",
        ),
    )
    line = billing_service.invoice_items.create(
        db_session,
        InvoiceItemCreate(invoice_id=inv.id, description="Orig", amount=100),
    )
    updated = billing_service.invoice_items.update(
        db_session, str(line.id), InvoiceItemUpdate(amount=200)
    )
    assert updated.amount == 200


# ── Payment Methods ──────────────────────────────────────


def test_create_payment_method(db_session, billing_customer):
    pm = billing_service.payment_methods.create(
        db_session,
        PaymentMethodCreate(
            customer_id=billing_customer.id,
            type="card",
            details={"last4": "4242", "brand": "visa"},
            is_default=True,
        ),
    )
    assert pm.details["last4"] == "4242"


def test_list_payment_methods_filter_type(db_session, billing_customer):
    billing_service.payment_methods.create(
        db_session,
        PaymentMethodCreate(
            customer_id=billing_customer.id,
            type="card",
        ),
    )
    items, total = billing_service.payment_methods.list(
        db_session,
        customer_id=str(billing_customer.id),
        type="card",
        is_active=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1


def test_update_payment_method(db_session, billing_customer):
    pm = billing_service.payment_methods.create(
        db_session,
        PaymentMethodCreate(customer_id=billing_customer.id, type="card"),
    )
    updated = billing_service.payment_methods.update(
        db_session, str(pm.id), PaymentMethodUpdate(is_default=True)
    )
    assert updated.is_default is True


# ── Payment Intents ──────────────────────────────────────


def test_create_payment_intent(db_session, billing_customer):
    pi = billing_service.payment_intents.create(
        db_session,
        PaymentIntentCreate(
            customer_id=billing_customer.id,
            amount=5000,
            currency="usd",
        ),
    )
    assert pi.amount == 5000
    assert pi.status.value == "requires_payment_method"


def test_update_payment_intent(db_session, billing_customer):
    pi = billing_service.payment_intents.create(
        db_session,
        PaymentIntentCreate(
            customer_id=billing_customer.id,
            amount=5000,
            currency="usd",
        ),
    )
    updated = billing_service.payment_intents.update(
        db_session, str(pi.id), PaymentIntentUpdate(status="succeeded")
    )
    assert updated.status.value == "succeeded"


# ── Usage Records ────────────────────────────────────────


def test_create_usage_record(db_session, billing_subscription_item):
    ur = billing_service.usage_records.create(
        db_session,
        UsageRecordCreate(
            subscription_item_id=billing_subscription_item.id,
            quantity=42,
            idempotency_key=f"key_{uuid.uuid4().hex}",
        ),
    )
    assert ur.quantity == 42


def test_list_usage_records(db_session, billing_subscription_item):
    billing_service.usage_records.create(
        db_session,
        UsageRecordCreate(
            subscription_item_id=billing_subscription_item.id,
            quantity=10,
            idempotency_key=f"key_{uuid.uuid4().hex}",
        ),
    )
    items, total = billing_service.usage_records.list(
        db_session,
        subscription_item_id=str(billing_subscription_item.id),
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1


# ── Coupons ──────────────────────────────────────────────


def test_create_coupon(db_session):
    coupon = billing_service.coupons.create(
        db_session,
        CouponCreate(
            name="Holiday Sale",
            code=f"HOLIDAY{uuid.uuid4().hex[:4].upper()}",
            percent_off=15,
            duration="once",
        ),
    )
    assert coupon.percent_off == 15


def test_list_coupons_filter_valid(db_session):
    billing_service.coupons.create(
        db_session,
        CouponCreate(
            name="Valid Coupon",
            code=f"VALID{uuid.uuid4().hex[:4].upper()}",
            percent_off=10,
            duration="once",
            valid=True,
        ),
    )
    items, total = billing_service.coupons.list(
        db_session,
        valid=True,
        code=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1


def test_update_coupon(db_session):
    coupon = billing_service.coupons.create(
        db_session,
        CouponCreate(
            name="Update Me",
            code=f"UPD{uuid.uuid4().hex[:4].upper()}",
            percent_off=5,
            duration="once",
        ),
    )
    updated = billing_service.coupons.update(
        db_session, str(coupon.id), CouponUpdate(percent_off=30)
    )
    assert updated.percent_off == 30


def test_delete_coupon(db_session):
    coupon = billing_service.coupons.create(
        db_session,
        CouponCreate(
            name="Del Me",
            code=f"DEL{uuid.uuid4().hex[:4].upper()}",
            amount_off=500,
            currency="usd",
            duration="once",
        ),
    )
    billing_service.coupons.delete(db_session, str(coupon.id))
    fetched = billing_service.coupons.get(db_session, str(coupon.id))
    assert fetched.valid is False


# ── Discounts ────────────────────────────────────────────


def test_create_discount(db_session, billing_coupon, billing_customer):
    disc = billing_service.discounts.create(
        db_session,
        DiscountCreate(
            coupon_id=billing_coupon.id,
            customer_id=billing_customer.id,
        ),
    )
    assert disc.coupon_id == billing_coupon.id


def test_list_discounts(db_session, billing_coupon, billing_customer):
    billing_service.discounts.create(
        db_session,
        DiscountCreate(
            coupon_id=billing_coupon.id,
            customer_id=billing_customer.id,
        ),
    )
    items, total = billing_service.discounts.list(
        db_session,
        customer_id=str(billing_customer.id),
        subscription_id=None,
        coupon_id=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1


def test_delete_discount(db_session, billing_coupon, billing_customer):
    disc = billing_service.discounts.create(
        db_session,
        DiscountCreate(
            coupon_id=billing_coupon.id,
            customer_id=billing_customer.id,
        ),
    )
    billing_service.discounts.delete(db_session, str(disc.id))
    with pytest.raises(HTTPException):
        billing_service.discounts.get(db_session, str(disc.id))


# ── Entitlements ─────────────────────────────────────────


def test_create_entitlement(db_session, billing_product):
    ent = billing_service.entitlements.create(
        db_session,
        EntitlementCreate(
            product_id=billing_product.id,
            feature_key=f"feat_{uuid.uuid4().hex[:8]}",
            value_type="numeric",
            value_numeric=500,
        ),
    )
    assert ent.value_numeric == 500


def test_list_entitlements_filter_product(db_session, billing_product):
    billing_service.entitlements.create(
        db_session,
        EntitlementCreate(
            product_id=billing_product.id,
            feature_key=f"feat_{uuid.uuid4().hex[:8]}",
            value_type="boolean",
        ),
    )
    items, total = billing_service.entitlements.list(
        db_session,
        product_id=str(billing_product.id),
        feature_key=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1


def test_update_entitlement(db_session, billing_product):
    ent = billing_service.entitlements.create(
        db_session,
        EntitlementCreate(
            product_id=billing_product.id,
            feature_key=f"feat_{uuid.uuid4().hex[:8]}",
            value_type="numeric",
            value_numeric=100,
        ),
    )
    updated = billing_service.entitlements.update(
        db_session, str(ent.id), EntitlementUpdate(value_numeric=999)
    )
    assert updated.value_numeric == 999


def test_delete_entitlement(db_session, billing_product):
    ent = billing_service.entitlements.create(
        db_session,
        EntitlementCreate(
            product_id=billing_product.id,
            feature_key=f"feat_{uuid.uuid4().hex[:8]}",
            value_type="unlimited",
        ),
    )
    billing_service.entitlements.delete(db_session, str(ent.id))
    with pytest.raises(HTTPException):
        billing_service.entitlements.get(db_session, str(ent.id))


# ── Webhook Events ───────────────────────────────────────


def test_create_webhook_event(db_session):
    evt = billing_service.webhook_events.create(
        db_session,
        WebhookEventCreate(
            provider="stripe",
            event_type="charge.succeeded",
            event_id=f"evt_{uuid.uuid4().hex}",
            payload={"amount": 1000},
        ),
    )
    assert evt.provider == "stripe"
    assert evt.status.value == "pending"


def test_update_webhook_event(db_session):
    evt = billing_service.webhook_events.create(
        db_session,
        WebhookEventCreate(
            provider="stripe",
            event_type="invoice.paid",
            event_id=f"evt_{uuid.uuid4().hex}",
        ),
    )
    updated = billing_service.webhook_events.update(
        db_session, str(evt.id), WebhookEventUpdate(status="processed")
    )
    assert updated.status.value == "processed"


def test_list_webhook_events_filter_provider(db_session):
    billing_service.webhook_events.create(
        db_session,
        WebhookEventCreate(
            provider="manual",
            event_type="test.event",
            event_id=f"evt_{uuid.uuid4().hex}",
        ),
    )
    items, total = billing_service.webhook_events.list(
        db_session,
        provider="manual",
        event_type=None,
        status=None,
        order_by="created_at",
        order_dir="asc",
        limit=50,
        offset=0,
    )
    assert len(items) >= 1
    assert total >= 1
    assert all(r.provider == "manual" for r in items)

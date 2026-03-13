"""Tests for billing API endpoints."""

import uuid


def test_api_create_product(client, auth_headers):
    resp = client.post(
        "/products",
        json={"name": "API Product", "description": "Test"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "API Product"
    assert data["is_active"] is True


def test_api_get_product(client, auth_headers, billing_product):
    resp = client.get(f"/products/{billing_product.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == billing_product.name


def test_api_list_products(client, auth_headers, billing_product):
    resp = client.get("/products", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["count"] >= 1
    assert "total" in data


def test_api_update_product(client, auth_headers, billing_product):
    resp = client.patch(
        f"/products/{billing_product.id}",
        json={"name": "Updated Product"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Product"


def test_api_delete_product(client, auth_headers):
    create_resp = client.post(
        "/products",
        json={"name": "Delete Me"},
        headers=auth_headers,
    )
    product_id = create_resp.json()["id"]
    resp = client.delete(f"/products/{product_id}", headers=auth_headers)
    assert resp.status_code == 204


def test_api_create_customer(client, auth_headers):
    resp = client.post(
        "/customers",
        json={"name": "Test Cust", "email": "cust@example.com"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test Cust"


def test_api_list_customers(client, auth_headers, billing_customer):
    resp = client.get("/customers", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


def test_api_create_price(client, auth_headers, billing_product):
    resp = client.post(
        "/prices",
        json={
            "product_id": str(billing_product.id),
            "currency": "usd",
            "unit_amount": 999,
            "type": "one_time",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["unit_amount"] == 999


def test_api_list_prices(client, auth_headers, billing_price):
    resp = client.get("/prices", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


def test_api_create_subscription(client, auth_headers, billing_customer):
    resp = client.post(
        "/subscriptions",
        json={"customer_id": str(billing_customer.id), "status": "active"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "active"


def test_api_list_subscriptions(client, auth_headers, billing_subscription):
    resp = client.get("/subscriptions", headers=auth_headers)
    assert resp.status_code == 200


def test_api_create_invoice(client, auth_headers, billing_customer):
    resp = client.post(
        "/invoices",
        json={
            "customer_id": str(billing_customer.id),
            "number": f"INV-{uuid.uuid4().hex[:8]}",
            "subtotal": 5000,
            "total": 5000,
            "amount_due": 5000,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["total"] == 5000


def test_api_list_invoices(client, auth_headers):
    resp = client.get("/invoices", headers=auth_headers)
    assert resp.status_code == 200


def test_api_create_payment_method(client, auth_headers, billing_customer):
    resp = client.post(
        "/payment-methods",
        json={
            "customer_id": str(billing_customer.id),
            "type": "card",
            "details": {"last4": "1234"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201


def test_api_create_payment_intent(client, auth_headers, billing_customer):
    resp = client.post(
        "/payment-intents",
        json={
            "customer_id": str(billing_customer.id),
            "amount": 2500,
            "currency": "usd",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["amount"] == 2500


def test_api_create_coupon(client, auth_headers):
    resp = client.post(
        "/coupons",
        json={
            "name": "API Coupon",
            "code": f"API{uuid.uuid4().hex[:4].upper()}",
            "percent_off": 10,
            "duration": "once",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["percent_off"] == 10


def test_api_list_coupons(client, auth_headers, billing_coupon):
    resp = client.get("/coupons", headers=auth_headers)
    assert resp.status_code == 200


def test_api_create_entitlement(client, auth_headers, billing_product):
    resp = client.post(
        "/entitlements",
        json={
            "product_id": str(billing_product.id),
            "feature_key": f"feat_{uuid.uuid4().hex[:8]}",
            "value_type": "boolean",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201


def test_api_list_entitlements(client, auth_headers):
    resp = client.get("/entitlements", headers=auth_headers)
    assert resp.status_code == 200


def test_api_create_webhook_event(client, auth_headers):
    resp = client.post(
        "/webhook-events",
        json={
            "provider": "stripe",
            "event_type": "test.event",
            "event_id": f"evt_{uuid.uuid4().hex}",
            "payload": {"test": True},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201


def test_api_list_webhook_events(client, auth_headers):
    resp = client.get("/webhook-events", headers=auth_headers)
    assert resp.status_code == 200


def test_api_get_nonexistent_product(client, auth_headers):
    resp = client.get(f"/products/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


def test_api_unauthorized_access(client):
    resp = client.get("/products")
    assert resp.status_code in (401, 403)

"""
Tests for the restocking endpoints:
- GET  /api/restocking/recommendations
- GET  /api/restocking/orders
- POST /api/restocking/orders
"""
import pytest

import mock_data


@pytest.fixture(autouse=True)
def restore_submitted_orders():
    """POST tests append to the shared in-memory list; restore it in place
    (main.py holds a reference to the same list object) so tests stay isolated."""
    snapshot = mock_data.submitted_orders[:]
    yield
    mock_data.submitted_orders[:] = snapshot


class TestRestockRecommendations:
    def test_zero_budget_returns_no_items(self, client):
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total_cost"] == 0
        assert data["max_budget"] > 0

    def test_max_budget_covers_every_shortfall(self, client):
        max_budget = client.get("/api/restocking/recommendations?budget=0").json()["max_budget"]
        data = client.get(f"/api/restocking/recommendations?budget={max_budget}").json()

        assert data["total_cost"] == pytest.approx(max_budget)
        assert data["remaining_budget"] == pytest.approx(0)
        # Every recommended quantity is the item's full shortfall
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        for item in data["items"]:
            f = forecasts[item["sku"]]
            assert item["quantity"] == f["forecasted_demand"] - f["quantity_on_hand"]

    def test_items_without_shortfall_are_excluded(self, client):
        data = client.get("/api/restocking/recommendations?budget=1000000").json()
        skus = {item["sku"] for item in data["items"]}
        # These forecasts have stock on hand >= forecasted demand
        assert not skus & {"BRG-102", "MTR-304", "PSU-501"}

    def test_mid_budget_prioritizes_increasing_and_partially_fills(self, client):
        budget = 5000
        data = client.get(f"/api/restocking/recommendations?budget={budget}").json()

        assert data["total_cost"] <= budget
        assert data["remaining_budget"] == pytest.approx(budget - data["total_cost"])
        assert all(item["trend"] == "increasing" for item in data["items"])
        # FLT-405 ($3,100) and GSK-203 ($1,215) fit fully; WDG-001 gets the
        # $685 left over as 16 units at $42.50
        quantities = {item["sku"]: item["quantity"] for item in data["items"]}
        assert quantities == {"FLT-405": 250, "GSK-203": 180, "WDG-001": 16}

    def test_line_totals_and_lead_times(self, client):
        data = client.get("/api/restocking/recommendations?budget=100000").json()
        for item in data["items"]:
            assert item["line_total"] == pytest.approx(item["unit_cost"] * item["quantity"])
            assert item["lead_time_days"] > 0

    def test_negative_budget_rejected(self, client):
        response = client.get("/api/restocking/recommendations?budget=-1")
        assert response.status_code == 422


class TestRestockOrders:
    def test_create_then_list(self, client):
        payload = {"items": [{"sku": "SNR-420", "quantity": 10}, {"sku": "CTL-330", "quantity": 2}]}
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201
        order = response.json()

        assert order["status"] == "Submitted"
        assert order["total_cost"] == pytest.approx(10 * 89.50 + 2 * 145.00)
        # Sensors = 7 days, Controllers = 12 days; the order takes the longest
        assert order["lead_time_days"] == 12
        assert order["expected_delivery"]

        listed = client.get("/api/restocking/orders").json()
        assert listed[0]["id"] == order["id"]

    def test_orders_listed_newest_first(self, client):
        first = client.post("/api/restocking/orders", json={"items": [{"sku": "GSK-203", "quantity": 1}]}).json()
        second = client.post("/api/restocking/orders", json={"items": [{"sku": "FLT-405", "quantity": 1}]}).json()
        ids = [o["id"] for o in client.get("/api/restocking/orders").json()]
        assert ids.index(second["id"]) < ids.index(first["id"])

    def test_server_prices_override_client(self, client):
        payload = {"items": [{"sku": "WDG-001", "quantity": 2, "unit_cost": 0.01}]}
        order = client.post("/api/restocking/orders", json=payload).json()
        assert order["items"][0]["unit_cost"] == 42.50
        assert order["total_cost"] == pytest.approx(85.00)

    @pytest.mark.parametrize("payload", [
        {"items": []},
        {"items": [{"sku": "NOPE-999", "quantity": 1}]},
        {"items": [{"sku": "WDG-001", "quantity": 0}]},
        {"items": [{"sku": "WDG-001", "quantity": -5}]},
    ])
    def test_invalid_orders_rejected(self, client, payload):
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 400
        assert client.get("/api/restocking/orders").json() == []

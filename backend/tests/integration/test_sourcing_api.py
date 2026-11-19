import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _token(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_sourcing_profile_and_cart(client: AsyncClient, users_and_memberships):
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    step = await client.get("/api/v1/sourcing/onboarding", headers=headers)
    assert step.status_code == 200, step.text
    assert step.json()["field"] == "business_type"
    assert step.json()["options"]

    step = await client.post(
        "/api/v1/sourcing/onboarding/answer",
        headers=headers,
        json={"answer": "Online store"},
    )
    assert step.status_code == 200, step.text
    assert step.json()["field"] == "location"
    # The reply reacts to what the person said and still asks the next question,
    # instead of dropping the answer and reading out the next prompt.
    assert "Online store" in step.json()["prompt"]
    assert step.json()["prompt"].endswith("?")

    for answer in ("Dhaka", "wireless earbuds"):
        step = await client.post(
            "/api/v1/sourcing/onboarding/answer",
            headers=headers,
            json={"answer": answer},
        )
        assert step.status_code == 200, step.text

    # An answer with no number in it asks the question again rather than answering
    # a chat message with a 400.
    step = await client.post(
        "/api/v1/sourcing/onboarding/answer",
        headers=headers,
        json={"answer": "no idea honestly"},
    )
    assert step.status_code == 200, step.text
    assert step.json()["field"] == "investment_budget"

    # "50k" is understood as 50,000.
    step = await client.post(
        "/api/v1/sourcing/onboarding/answer",
        headers=headers,
        json={"answer": "50k"},
    )
    assert step.status_code == 200, step.text
    assert step.json()["field"] == "team_size"
    assert float(step.json()["profile"]["investment_budget"]) == 50000

    response = await client.put(
        "/api/v1/sourcing/profile",
        headers=headers,
        json={
            "business_type": "Online store",
            "location": "Dhaka",
            "product_idea": "wireless earbuds",
            "investment_budget": 50000,
            "team_size": "2",
            "account_type": "Business",
            "experience": "Some experience",
            "sales_channels": ["Website", "Facebook"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["product_idea"] == "wireless earbuds"

    response = await client.put(
        "/api/v1/sourcing/profile",
        headers=headers,
        json={"location": "Chattogram"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["location"] == "Chattogram"
    assert response.json()["product_idea"] == "wireless earbuds"

    response = await client.post(
        "/api/v1/sourcing/cart",
        headers=headers,
        json={
            "listing_id": "listing-001",
            "marketplace": "Alibaba",
            "title": "Wireless earbuds",
            "unit_price": 1200,
            "currency": "BDT",
        },
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        "/api/v1/sourcing/products",
        headers=headers,
        json={"keyword": "Wireless Earbuds"},
    )
    assert response.status_code == 200, response.text

    dashboard = await client.get("/api/v1/sourcing/dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["tracked_product_count"] == 1
    assert dashboard.json()["cart_count"] == 1

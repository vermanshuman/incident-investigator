"""Synthetic customer traffic against the checkout service.

Mix: create cart -> checkout (75% with a delivery address, 25% store pickup
without one) -> occasional payment retry and cart lookups. Runs `concurrency`
workers for `seconds`, returns a summary of status codes.
"""

import asyncio
import random
import time
from collections import Counter

import httpx

SKUS = ["SKU-001", "SKU-002", "SKU-003", "SKU-004", "SKU-005", "SKU-006"]
REGIONS = ["in-west", "in-south", "in-north", "eu-central", "us-east"]
ADDRESSES = [
    {"line1": "1 MG Road", "city": "Pune", "country": "IN"},
    {"line1": "22 Brigade Rd", "city": "Bengaluru", "country": "IN"},
    {"line1": "5 Hauptstrasse", "city": "Berlin", "country": "DE"},
    {"line1": "77 Broadway", "city": "New York", "country": "US"},
]


async def _customer(client: httpx.AsyncClient, deadline: float, stats: Counter, rng: random.Random):
    while time.time() < deadline:
        region = rng.choice(REGIONS)
        headers = {"x-region": region}
        try:
            items = [{"sku": rng.choice(SKUS), "qty": rng.randint(1, 3)} for _ in range(rng.randint(1, 3))]
            r = await client.post("/cart", json={"items": items, "region": region}, headers=headers)
            stats[f"POST /cart {r.status_code}"] += 1
            if r.status_code != 201:
                continue
            cart_id = r.json()["cart_id"]

            if rng.random() < 0.3:
                r = await client.get(f"/cart/{cart_id}", headers=headers)
                stats[f"GET /cart {r.status_code}"] += 1

            body = {"cart_id": cart_id, "payment_method": rng.choice(["card", "upi", "card"])}
            if rng.random() < 0.75:
                body["shipping_address"] = {**rng.choice(ADDRESSES), "region": region}
            r = await client.post("/checkout", json=body, headers=headers)
            stats[f"POST /checkout {r.status_code}"] += 1

            if r.status_code == 502 and rng.random() < 0.5:
                order_id = r.json().get("detail", "")  # not available; skip retry lookup
                del order_id
        except httpx.HTTPError as exc:
            stats[f"client error {type(exc).__name__}"] += 1
        await asyncio.sleep(rng.uniform(0.05, 0.4))


async def generate(base_url: str, seconds: int, concurrency: int, seed: int | None = None) -> Counter:
    rng = random.Random(seed)
    stats: Counter = Counter()
    deadline = time.time() + seconds
    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
        await asyncio.gather(*[_customer(client, deadline, stats, rng) for _ in range(concurrency)])
    return stats


def run(base_url: str, seconds: int, concurrency: int, seed: int | None = None) -> Counter:
    return asyncio.run(generate(base_url, seconds, concurrency, seed))

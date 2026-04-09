"""MCP server exposing the check_credit_score tool."""

import hashlib
import random

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("credit-card-tools", host="0.0.0.0", port=8080)


@mcp.tool()
def check_credit_score(
    ssn_last4: str = "0000",
    first_name: str = "John",
    last_name: str = "Doe",
    date_of_birth: str = "1985-01-15",
) -> dict:
    """Perform a credit score check (simulated Equifax-style report).

    Uses the customer's last 4 digits of SSN, name, and date of birth to
    pull a credit report. Returns a FICO score (300-850), rating tier,
    and key credit factors based on standard US credit bureau data.

    Args:
        ssn_last4: Last 4 digits of the customer's Social Security Number.
        first_name: Customer's first name.
        last_name: Customer's last name.
        date_of_birth: Customer's date of birth (YYYY-MM-DD).
    """
    print(
        f"check_credit_score tool called for {first_name} {last_name} "
        f"(SSN ***-**-{ssn_last4}, DOB {date_of_birth})"
    )

    # Deterministic but varied score seeded from inputs so the same
    # customer always gets the same result within a session.
    seed = hashlib.sha256(
        f"{ssn_last4}{first_name}{last_name}{date_of_birth}".encode()
    ).hexdigest()
    rng = random.Random(seed)

    # FICO score distribution roughly mirrors US population:
    #   ~20% Exceptional (800-850), ~25% Very Good (740-799),
    #   ~21% Good (670-739), ~18% Fair (580-669), ~16% Poor (300-579)
    score = rng.choices(
        population=[
            rng.randint(800, 850),
            rng.randint(740, 799),
            rng.randint(670, 739),
            rng.randint(580, 669),
            rng.randint(300, 579),
        ],
        weights=[20, 25, 21, 18, 16],
        k=1,
    )[0]

    if score >= 800:
        rating = "Exceptional"
    elif score >= 740:
        rating = "Very Good"
    elif score >= 670:
        rating = "Good"
    elif score >= 580:
        rating = "Fair"
    else:
        rating = "Poor"

    num_accounts = rng.randint(3, 25)
    credit_utilization = rng.randint(1, 85)
    oldest_account_years = rng.randint(1, 30)
    recent_inquiries = rng.randint(0, 8)
    late_payments = rng.randint(0, 6) if score < 740 else 0
    total_debt = rng.randint(500, 120000)
    available_credit = rng.randint(2000, 100000)
    collections = rng.randint(0, 3) if score < 670 else 0
    bankruptcies = 1 if score < 500 and rng.random() < 0.3 else 0

    factors = []
    if credit_utilization > 30:
        factors.append("High credit utilization ratio")
    if late_payments > 0:
        factors.append(f"{late_payments} late payment(s) on record")
    if recent_inquiries > 3:
        factors.append("Too many recent credit inquiries")
    if oldest_account_years < 3:
        factors.append("Limited credit history length")
    if collections > 0:
        factors.append(f"{collections} account(s) in collections")
    if bankruptcies > 0:
        factors.append("Bankruptcy on record")
    if num_accounts < 5:
        factors.append("Few active credit accounts")
    if not factors:
        factors.append("Strong payment history")
        factors.append("Low credit utilization")
        factors.append("Long credit history")

    result = {
        "bureau": "Equifax",
        "report_type": "Soft Inquiry (no impact to score)",
        "customer": f"{first_name} {last_name}",
        "fico_score": score,
        "rating": rating,
        "score_range": "300-850",
        "credit_utilization_pct": credit_utilization,
        "total_accounts": num_accounts,
        "oldest_account_years": oldest_account_years,
        "recent_inquiries_last_2yr": recent_inquiries,
        "late_payments": late_payments,
        "collections": collections,
        "bankruptcies": bankruptcies,
        "total_debt_usd": total_debt,
        "available_credit_usd": available_credit,
        "key_factors": factors,
    }

    print(f"check_credit_score → FICO {score} ({rating})")
    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

"""Scenario math only. Source views are never treated as paid views or revenue."""
import math


def required_views(target, net_per_thousand, monthly_cost=0):
    if target < 0 or monthly_cost < 0 or net_per_thousand <= 0:
        raise ValueError("Expected nonnegative target/cost and a positive net rate")
    return math.ceil((target + monthly_cost) * 1000 / net_per_thousand)


def report():
    lines = [
        "### $500/month planning — scenarios, not earnings forecasts",
        "No verified payout data is connected. Earnings and YPP status are unknown.",
        "Public view counts below are research signals, not qualified paid views.",
        "",
        "| Hypothetical net rate / 1,000 qualified views | Views needed for $500, before tax |",
        "| --- | ---: |",
    ]
    for rate in (.05, .10, .90, 1.80):
        lines.append(f"| ${rate:.2f} | {required_views(500, rate):,} |")
    lines += [
        "",
        "The $0.05/$0.10 rows are illustrative Shorts rates, not measured channel RPM.",
        "The $0.90/$1.80 rows illustrate $1/$2 campaign rates after a 10% fee.",
        "No campaign offer, acceptance, remaining budget, or payout is implied.",
        "Include monthly tool/storage costs before calculating profit: (500 + costs) × 1000 / net rate.",
        "Permission to clip does not establish YouTube monetization eligibility.",
        "Keep the five-post cap while testing. Compare similarly aged uploads and confirmed payouts before increasing spend.",
    ]
    return lines

#!/usr/bin/env python3
"""Extract all lost bets from ledger for analysis."""
import json
from collections import Counter

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/bet_ledger.json') as f:
    data = json.load(f)

bets = data.get('bets', [])
lost = [b for b in bets if b.get('status') == 'lost']

print(f"Total bets: {len(bets)}")
print(f"Total lost: {len(lost)}")

# Count by match
match_counter = Counter(b['match'] for b in lost)
print("\n=== LOSSES BY FIXTURE ===")
for match, count in match_counter.most_common():
    print(f"  {match}: {count}")

# Count by market
market_counter = Counter(b['market'] for b in lost)
print("\n=== LOSSES BY MARKET ===")
for market, count in market_counter.most_common():
    print(f"  {market}: {count}")

# Count by season
season_counter = Counter(b.get('season_name', 'unknown') for b in lost)
print("\n=== LOSSES BY SEASON ===")
for season, count in season_counter.most_common():
    print(f"  {season}: {count}")

# Find matchday ranges for losses
md_counter = Counter(b.get('matchday', 0) for b in lost)
print("\n=== LOSSES BY MATCHDAY ===")
for md in sorted(md_counter.keys()):
    print(f"  MD {md}: {md_counter[md]}")

# Show details
print("\n=== LOSS DETAILS ===")
for b in lost[:30]:
    print(f"  {b['match']} | {b['market']} | MD {b.get('matchday')} | Result: {b['result']} | Season: {b.get('season_name')}")

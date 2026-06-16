import json, os

LEDGER_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/signals/bet_ledger.json"

if os.path.exists(LEDGER_PATH):
    with open(LEDGER_PATH) as f:
        ledger = json.load(f)
    
    fixed_count = 0
    for bet in ledger.get("bets", []):
        if bet.get("settled") and bet.get("status") == "lost":
            # Check if any leg has 0:0 but market was Over
            has_suspicious_zero = False
            legs = bet.get("legs", [])
            if not legs:
                if bet.get("result") == "0:0" and "over" in bet.get("market", "").lower():
                    has_suspicious_zero = True
            else:
                for leg in legs:
                    if leg.get("result") == "0:0" and "over" in leg.get("market", "").lower():
                        has_suspicious_zero = True
                        break
            
            if has_suspicious_zero:
                bet["settled"] = False
                bet.pop("status", None)
                bet.pop("payout", None)
                bet.pop("profit", None)
                fixed_count += 1
            
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)
    print(f"Fixed {fixed_count} suspicious lost bets in ledger.")
else:
    print("Ledger not found.")

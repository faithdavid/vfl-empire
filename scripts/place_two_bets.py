#!/usr/bin/env python3
"""
Place TWO single bets on MSport via CDP browser automation.
Bet 1: Aston Villa vs Crystal Palace - Over 1.5 Goals @ 1.25, ₦50 (LIVE NOW)
Bet 2: Wolverhampton vs Aston Villa - Over 1.5 Goals @ 1.25, ₦50 (starts in ~4min)
"""
import json, sys, time
sys.path.insert(0, '.')
from browser_bet_placer import login, place_bet, get_balance, ws_send, CHROME_WS

def main():
    # Connect CDP
    ws_send("Page.enable")
    ws_send("Runtime.enable")
    print("Connected to Chromium CDP")

    # Login
    login()
    print("Logged in to MSport")

    # Check initial balance
    bal = get_balance()
    print(f"Initial balance: {bal}")

    # ── Bet 1: Aston Villa vs Crystal Palace (LIVE NOW) ──
    print("\n========== BET 1: Aston Villa vs Crystal Palace ==========")
    result1 = place_bet("Aston Villa", "Crystal Palace", "Over 1.5 Goals", 1.25, 50)
    print(f"Bet 1 result: {json.dumps(result1, indent=2)}")
    time.sleep(3)

    # ── Bet 2: Wolverhampton vs Aston Villa ──
    print("\n========== BET 2: Wolverhampton vs Aston Villa ==========")
    result2 = place_bet("Wolverhampton", "Aston Villa", "Over 1.5 Goals", 1.25, 50)
    print(f"Bet 2 result: {json.dumps(result2, indent=2)}")

    # Final balance
    time.sleep(2)
    final_bal = get_balance()
    print(f"\nFinal balance: {final_bal}")

    # Close WS
    if CHROME_WS:
        CHROME_WS.close()

    print(f"\n✅ Both bets placed.\n{json.dumps({'bet1': result1, 'bet2': result2, 'final_balance': final_bal}, indent=2)}")

if __name__ == "__main__":
    main()

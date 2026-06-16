#!/usr/bin/env python3
import sys, json, time
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import place_parlay

def main():
    legs = [
        {
            "home": "Leeds",
            "away": "Wolverhampton",
            "market": "Over 1.5 Goals",
            "odds": 1.45
        },
        {
            "home": "Chelsea",
            "away": "Manchester Red",
            "market": "Over 1.5 Goals",
            "odds": 1.22
        }
    ]
    stake = 87.42
    matchday = 20
    
    print(f"Placing active parlay: {legs} on MD{matchday} with stake {stake}")
    res = place_parlay(legs, stake, target_md=matchday)
    print("Placement Result:")
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()

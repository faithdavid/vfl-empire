#!/usr/bin/env python3
import sys, time, logging
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.msport_client import get_results

def scan(start, end):
    print(f"Scanning range {start} to {end}...")
    for i in range(start, end):
        try:
            res = get_results(f'vf:season:{i}', 1)
            if res:
                print(f"FOUND VALID SEASON: {i}")
                return i
        except:
            pass
        if i % 100 == 0:
            print(f"Reached {i}...")
    return None

if __name__ == "__main__":
    # Scan backwards from 3091775 (5106)
    scan(3088000, 3091775)

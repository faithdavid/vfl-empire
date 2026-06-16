#!/usr/bin/env python3
import sys, time
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.msport_client import get_results

def jump_scan(start, end, step=25):
    print(f"Jump scanning range {start} to {end} with step {step}...")
    found = []
    for i in range(end, start, -step):
        try:
            res = get_results(f'vf:season:{i}', 1)
            if res:
                print(f"FOUND: {i}")
                found.append(i)
                # If found, check around it
                for j in range(i-5, i+6):
                    if j != i:
                        r = get_results(f'vf:season:{j}', 1)
                        if r:
                            print(f"FOUND NEAR: {j}")
                            found.append(j)
        except:
            pass
        if i % 500 == 0:
            print(f"Reached {i}...")
    return sorted(list(set(found)))

if __name__ == "__main__":
    # Scan from 3091775 backwards to 3000000
    jump_scan(3000000, 3091775, step=50)

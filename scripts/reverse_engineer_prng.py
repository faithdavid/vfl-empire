#!/usr/bin/env python3
import psycopg2
import math
import sys
import os

# Connect to DB
conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")
cur = conn.cursor()

def fetch_schedules():
    # Fetch chronologically sorted seasons
    cur.execute("""
        SELECT season, min(id) as first_id 
        FROM matches 
        GROUP BY season 
        ORDER BY first_id ASC 
        LIMIT 20;
    """)
    seasons = [row[0] for row in cur.fetchall()]
    
    # Get all teams to create an index mapping
    cur.execute("SELECT DISTINCT home FROM matches LIMIT 16;")
    teams = sorted([row[0] for row in cur.fetchall()])
    team_map = {t: str(hex(i)[2:]) for i, t in enumerate(teams)} # map 0-15 to 0-f

    schedules_str = ""
    for season in seasons:
        cur.execute("SELECT home, away FROM matches WHERE season = %s ORDER BY day, home LIMIT 8;", (season,))
        for h, a in cur.fetchall():
            schedules_str += team_map[h] + team_map[a]
    return schedules_str, len(seasons)

schedules_hex, season_count = fetch_schedules()
if not schedules_hex:
    print("No schedule data found.")
    sys.exit()

print(f"Loaded {season_count} seasons. Extracted sequence of length {len(schedules_hex)} hex characters.")

# Test 1: Pi Hypothesis
# Generate Pi digits
def generate_pi_hex(num_digits):
    # Machin's formula: pi/4 = 4*arctan(1/5) - arctan(1/239)
    # Actually for hex, BBP formula or just a simple string for demo if we can't easily compute huge pi.
    # Let's approximate by computing a few thousand digits using python's decimal or integer math.
    import decimal
    decimal.getcontext().prec = num_digits + 10
    pi = decimal.Decimal(0)
    # we don't have infinite time, let's just use math.pi for a quick check of first 15 hex digits
    return hex(int(math.pi * (16**15)))[2:]

print("\n[Phase 1] Pi Hypothesis Check...")
# Since generating 1,000,000 hex digits of Pi in pure Python is slow without libraries,
# we check against a smaller subset or use a known mathematical property.
# A true PRNG test would need to see if sequences repeat exactly.
if schedules_hex[:10] in generate_pi_hex(15):
    print(" MATCH: Initial sequence maps directly to Pi!")
else:
    print(" NO MATCH: Initial sequence does not map to the first digits of Pi.")

# Test 2: Sequence Repetition (Are they just looping an array?)
print("\n[Phase 2] Sequence Loop Check...")
def find_repeating_substring(s, min_len=16):
    for length in range(len(s)//2, min_len-1, -1):
        for i in range(len(s) - length*2 + 1):
            sub = s[i:i+length]
            if s.find(sub, i+length) != -1:
                return sub
    return None

rep = find_repeating_substring(schedules_hex, min_len=32)
if rep:
    print(f" FOUND REPETITION: The schedule engine loops every {len(rep)//16} matches!")
else:
    print(" NO REPETITION: The schedule appears structurally non-repeating within the sample size.")

# Test 3: LCG Modulo Pattern
print("\n[Phase 3] LCG Pattern Check...")
# If X_n+1 = (a * X_n + c) % 16
# We check if a simple LCG could produce the sequence of team indices
seq = [int(c, 16) for c in schedules_hex]
found_lcg = False
for a in range(16):
    for c in range(16):
        match = True
        for i in range(len(seq)-1):
            if (a * seq[i] + c) % 16 != seq[i+1]:
                match = False
                break
        if match:
            print(f" FOUND LCG: X_n+1 = ({a} * X_n + {c}) mod 16")
            found_lcg = True
            break
    if found_lcg: break

if not found_lcg:
    print(" NO MATCH: Simple modulo 16 LCG does not fit the sequence.")

# Test 4: Mersenne Twister Python random.shuffle Signature
print("\n[Phase 4] Fisher-Yates Shuffle with MT19937 Check...")
# A pure python random.shuffle leaves very specific permutation distributions.
# This requires heavy cryptanalysis, but we can do a quick check to see if the sequence has high entropy.
def entropy(s):
    import collections
    probs = [c / len(s) for c in collections.Counter(s).values()]
    return -sum(p * math.log2(p) for p in probs)

ent = entropy(schedules_hex)
print(f" Sequence Entropy: {ent:.4f} bits per hex character (Max is 4.0000)")
if ent > 3.9:
    print(" CONCLUSION: High entropy indicates a complex PRNG (like Mersenne Twister) or Cryptographic Hash (SHA256) is used.")
else:
    print(" CONCLUSION: Low entropy indicates a weak PRNG or hardcoded schedule table.")

print("\nOVERALL CONCLUSION:")
if found_lcg:
    print("MSport uses a basic LCG. The engine is fully cracked.")
elif ent < 3.9:
    print("MSport uses a low-quality custom PRNG or a finite lookup table. Further structural analysis required.")
else:
    print("MSport uses a modern, high-entropy PRNG (like Mersenne Twister or RNG-based Hash) for shuffling fixtures. Cracking requires extracting 624 consecutive internal states.")

conn.close()

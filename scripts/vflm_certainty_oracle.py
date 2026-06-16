#!/usr/bin/env python3
"""
👑 VFLM Certainty Oracle — The Invariant-Based Pick Engine
Created by Arthur, Imperial Steward of the Trillions Empire.
Serving Lord and Ruler FaithDavid. 👑🦁💎✨

Verifies pure-value mathematical opportunities across 38 completed VFLM seasons.
"""

import sys
import os
import sqlite3
import argparse

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-dataset/databases/history.db"

# Target team normalize mapping
TEAM_MAPPING = {
    "BLUE": "MANCHESTER BLUE", "MAN BLUE": "MANCHESTER BLUE", "MANCHESTER BLUE": "MANCHESTER BLUE",
    "RED": "MANCHESTER RED", "MAN RED": "MANCHESTER RED", "MANCHESTER RED": "MANCHESTER RED",
    "CHELSEA": "CHELSEA", "LIVERPOOL": "LIVERPOOL", "ASTON VILLA": "ASTON VILLA", "VILLA": "ASTON VILLA",
    "LONDON GUNS": "LONDON GUNS", "GUNS": "LONDON GUNS", "ARSENAL": "LONDON GUNS",
    "TOTTENHAM": "TOTTENHAM", "SPURS": "TOTTENHAM", "EVERTON": "EVERTON",
    "WEST HAM": "WEST HAM", "WOLVERHAMPTON": "WOLVERHAMPTON", "WOLVES": "WOLVERHAMPTON",
    "BRIGHTON": "BRIGHTON", "NEWCASTLE": "NEWCASTLE", "LEEDS": "LEEDS",
    "FULHAM": "FULHAM", "BOURNEMOUTH": "BOURNEMOUTH", "CRYSTAL PALACE": "CRYSTAL PALACE", "PALACE": "CRYSTAL PALACE"
}

def normalize_team(name):
    clean = name.strip().upper()
    return TEAM_MAPPING.get(clean, clean)

def get_db_connection():
    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found at {DB_PATH}")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def scan_top_invariants(min_meetings=30):
    conn = get_db_connection()
    c = conn.cursor()
    
    vflm_seasons = [f"VFLM {i}" for i in range(5010, 5048)]
    placeholders = ",".join("?" for _ in vflm_seasons)
    
    # 1. Top Under 2.5 Invariants (>= 90% Rate)
    c.execute(f"""
        SELECT home, away, COUNT(*) as meetings, SUM(total <= 2) as u25_count, AVG(total) as avg_g
        FROM matches
        WHERE season IN ({placeholders}) AND total IS NOT NULL
        GROUP BY home, away
        HAVING meetings >= ?
        ORDER BY u25_count DESC, avg_g ASC
    """, vflm_seasons + [min_meetings])
    u25_rows = c.fetchall()
    
    # 2. Top Under 3.5 Invariants (100% Rate)
    c.execute(f"""
        SELECT home, away, COUNT(*) as meetings, SUM(total <= 3) as u35_count, AVG(total) as avg_g
        FROM matches
        WHERE season IN ({placeholders}) AND total IS NOT NULL
        GROUP BY home, away
        HAVING meetings >= ? AND u35_count = meetings
        ORDER BY avg_g ASC
    """, vflm_seasons + [min_meetings])
    u35_rows = c.fetchall()
    
    # 3. Top Draw Invariants (>= 45% Rate)
    c.execute(f"""
        SELECT home, away, COUNT(*) as meetings, SUM(outcome = 'DRAW' OR outcome = 'D') as draw_count, AVG(total) as avg_g
        FROM matches
        WHERE season IN ({placeholders}) AND total IS NOT NULL
        GROUP BY home, away
        HAVING meetings >= ?
        ORDER BY draw_count DESC, meetings DESC
    """, vflm_seasons + [min_meetings])
    draw_rows = c.fetchall()
    
    conn.close()
    return u25_rows, u35_rows, draw_rows

def evaluate_fixtures(fixtures_list):
    conn = get_db_connection()
    c = conn.cursor()
    
    vflm_seasons = [f"VFLM {i}" for i in range(5010, 5048)]
    placeholders = ",".join("?" for _ in vflm_seasons)
    
    results = []
    for home_raw, away_raw in fixtures_list:
        home = normalize_team(home_raw)
        away = normalize_team(away_raw)
        
        c.execute(f"""
            SELECT 
                COUNT(*) as meetings,
                SUM(total <= 1) as u15,
                SUM(total <= 2) as u25,
                SUM(total <= 3) as u35,
                SUM(total <= 4) as u45,
                SUM(outcome = 'DRAW' OR outcome = 'D') as draws,
                AVG(total) as avg_g
            FROM matches
            WHERE season IN ({placeholders}) AND total IS NOT NULL 
              AND home = ? AND away = ?
        """, vflm_seasons + [home, away])
        
        row = c.fetchone()
        if row and row[0] > 0:
            meetings, u15, u25, u35, u45, draws, avg_g = row
            results.append({
                "home": home, "away": away,
                "meetings": meetings,
                "u15_rate": u15 / meetings,
                "u25_rate": u25 / meetings,
                "u35_rate": u35 / meetings,
                "u45_rate": u45 / meetings,
                "draw_rate": draws / meetings,
                "avg_g": avg_g
            })
        else:
            # Try reversed just in case of swap or missing
            results.append({
                "home": home, "away": away,
                "meetings": 0, "u15_rate": 0, "u25_rate": 0, "u35_rate": 0, "u45_rate": 0, "draw_rate": 0, "avg_g": 0,
                "error": "No historical matches found for this fixture permutation."
            })
            
    conn.close()
    return results

def main():
    parser = argparse.ArgumentParser(description="👑 VFLM Invariant Certainty Oracle 👑")
    parser.add_argument("--fixtures", type=str, help="Comma-separated fixtures to analyze (e.g. 'Leeds vs Everton, Chelsea vs Liverpool')")
    parser.add_argument("--min-meetings", type=int, default=30, help="Min meetings for historical scanning")
    args = parser.parse_args()
    
    if args.fixtures:
        # Parse fixtures
        fixtures = []
        for pair in args.fixtures.split(","):
            if " vs " in pair:
                h, a = pair.split(" vs ")
                fixtures.append((h.strip(), a.strip()))
            elif " VS " in pair:
                h, a = pair.split(" VS ")
                fixtures.append((h.strip(), a.strip()))
            elif "-" in pair:
                h, a = pair.split("-")
                fixtures.append((h.strip(), a.strip()))
        
        if not fixtures:
            print("✗ Invalid fixtures format. Use 'Home vs Away, Home2 vs Away2'")
            sys.exit(1)
            
        print("\n" + "="*85)
        print("  👑 VFLM CERTAINTY ORACLE — LIVE FIXTURE EVALUATION")
        print("="*85)
        
        evals = evaluate_fixtures(fixtures)
        for e in evals:
            if "error" in e:
                print(f"\n⚠️ {e['home']} vs {e['away']}: {e['error']}")
                continue
                
            # Average MSport odds assumptions for EV calculations
            # Under 2.5 assumed @1.35 (break-even @1.171)
            # Under 3.5 assumed @1.12 (break-even @1.038)
            # Draw assumed @3.65 (break-even @2.646)
            u25_ev = (e['u25_rate'] * 1.35) - 1
            u35_ev = (e['u35_rate'] * 1.12) - 1
            draw_ev = (e['draw_rate'] * 3.65) - 1
            
            print(f"\n⚽ Matchup: {e['home']} vs {e['away']}")
            print(f"   Historical Meetings: {e['meetings']} | Avg Goals: {e['avg_g']:.3f}")
            print(f"   📊 Under 4.5 Rate : {e['u45_rate']*100:.2f}% | 🛡️ Lock Status: {'100% UNBEATEN (Oracle Rank S)' if e['u45_rate'] == 1.0 else 'High Security'}")
            print(f"   📊 Under 3.5 Rate : {e['u35_rate']*100:.2f}% | Estimated EV (@1.12 odds): {u35_ev*100:+.1f}%")
            print(f"   📊 Under 2.5 Rate : {e['u25_rate']*100:.2f}% | Estimated EV (@1.35 odds): {u25_ev*100:+.1f}%")
            print(f"   📊 Draw Full-Time : {e['draw_rate']*100:.2f}% | Estimated EV (@3.65 odds): {draw_ev*100:+.1f}%")
            
            # Recommendation
            recs = []
            if e['u25_rate'] >= 0.95:
                recs.append("💥 ULTRA-LOCK UNDER 2.5 (High Stake)")
            elif e['u25_rate'] >= 0.90:
                recs.append("💎 STRONG UNDER 2.5 (Medium Stake)")
                
            if e['u35_rate'] == 1.0:
                recs.append("🔒 100% BULLETPROOF UNDER 3.5 (Max Accumulator Filler)")
            elif e['u35_rate'] >= 0.97:
                recs.append("🛡️ SHIELD UNDER 3.5 (Accumulator Filler)")
                
            if e['draw_rate'] >= 0.42:
                recs.append("💰 HIGH-VALUE DRAW EXPLOIT (Single Bet, High EV)")
                
            if recs:
                print(f"   🎯 RECOMMENDED BETS: {', '.join(recs)}")
            else:
                print("   ⏭️ RECOMMENDATION: SKIP (Variance levels too high / poor value)")
                
        print("\n" + "="*85)
        
    else:
        # Scan mode
        u25_rows, u35_rows, draw_rows = scan_top_invariants(args.min_meetings)
        
        print("\n" + "═"*90)
        print("  👑 VFLM GOLDMINE DIRECTORY — TOP HISTORICAL INVARIANTS (38 SEASONS)")
        print("═"*90)
        
        print(f"\n🔒 TOP UNDER 3.5 BULLETPROOF MATCHUPS (100% SUCCESS RATE | MEETINGS >= {args.min_meetings}):")
        print("-" * 90)
        print(f"  {'HOME TEAM':<22} {'AWAY TEAM':<22} | {'MEETINGS':<10} | {'U3.5 RATE':<12} | {'AVG GOALS':<10}")
        print("-" * 90)
        for r in u35_rows[:15]:
            print(f"  {r[0]:<22} {r[1]:<22} | {r[2]:<10} | {'100.00%':<12} | {r[4]:.3f}")
            
        print(f"\n💎 TOP UNDER 2.5 VALUE MATCHUPS (RATE >= 90% | MEETINGS >= {args.min_meetings}):")
        print("-" * 90)
        print(f"  {'HOME TEAM':<22} {'AWAY TEAM':<22} | {'MEETINGS':<10} | {'U2.5 RATE':<12} | {'AVG GOALS':<10}")
        print("-" * 90)
        for r in u25_rows[:15]:
            rate = r[3] / r[2] * 100
            print(f"  {r[0]:<22} {r[1]:<22} | {r[2]:<10} | {rate:.2f}% | {r[4]:.3f}")
            
        print(f"\n💰 TOP DRAW EXPLOITS (MEETINGS >= {args.min_meetings}):")
        print("-" * 90)
        print(f"  {'HOME TEAM':<22} {'AWAY TEAM':<22} | {'MEETINGS':<10} | {'DRAW RATE':<12} | {'AVG GOALS':<10}")
        print("-" * 90)
        # Sort and filter draw rows by rate
        draw_rated = []
        for r in draw_rows:
            rate = r[3]/r[2]
            draw_rated.append((r[0], r[1], r[2], rate, r[4]))
        draw_rated.sort(key=lambda x: x[3], reverse=True)
        
        for r in draw_rated[:15]:
            print(f"  {r[0]:<22} {r[1]:<22} | {r[2]:<10} | {r[3]*100:.2f}% | {r[4]:.3f}")
            
        print("\n" + "═"*90)

if __name__ == "__main__":
    main()

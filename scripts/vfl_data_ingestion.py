#!/usr/bin/env python3
"""
VFL Data Ingestion Engine — Unifies ALL raw data into history.db
"""
import json, os, re, sqlite3
from collections import defaultdict

BASE = os.path.expanduser('~/Documents/Projects/vfl-data')
DB_PATH = os.path.join(BASE, 'databases/history.db')
ODDS_DIR = os.path.expanduser('~/Documents/Projects/vfl-extracted/odds')
RESULTS_DIR = os.path.expanduser('~/Documents/Projects/vfl-extracted/results')
H2H_PATH = os.path.join(BASE, 'analysis/h2h_matchup_patterns.json')
VFL_ANALYSIS_DIR = os.path.expanduser('~/Documents/Projects/vfl-analysis')

def ingest_odds_files():
    """Parse all raw odds text files and insert into history.db"""
    count = 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for fname in sorted(os.listdir(ODDS_DIR)):
        if not fname.endswith('.txt'): continue
        fpath = os.path.join(ODDS_DIR, fname)
        
        with open(fpath) as f:
            content = f.read()
        
        # Parse each MATCH block
        blocks = re.split(r'={5,}\s*MATCH #\d+ ={5,}', content)
        for block in blocks[1:]:  # Skip pre-match header
            # Extract season ID
            season_match = re.search(r'seasonId=vf:season:(\d+)', block)
            if not season_match: continue
            season_id = f"vf:season:{season_match.group(1)}"
            
            # Extract match day
            md_match = re.search(r'matchDay=(\d+)', block)
            if not md_match: continue
            md = int(md_match.group(1))
            
            # Extract season name
            sname_match = re.search(r'"seasonName":\s*"([^"]+)"', block)
            season_name = sname_match.group(1) if sname_match else ''
            
            # Extract events with odds
            events = re.finditer(
                r'"awayTeam":\s*"([^"]+)".*?'
                r'"homeTeam":\s*"([^"]+)".*?'
                r'"description":\s*"1x2".*?'
                r'"description":\s*"Home",\s*"id":\s*"[^"]*",\s*"isActive":\s*\d+,\s*"odds":\s*"([\d.]+)".*?'
                r'"description":\s*"Draw",\s*"id":\s*"[^"]*",\s*"isActive":\s*\d+,\s*"odds":\s*"([\d.]+)".*?'
                r'"description":\s*"Away",\s*"id":\s*"[^"]*",\s*"isActive":\s*\d+,\s*"odds":\s*"([\d.]+)"',
                block, re.DOTALL
            )
            
            for ev in events:
                away = ev.group(1).upper().strip()
                home = ev.group(2).upper().strip()
                oh = float(ev.group(3))
                od = float(ev.group(4))
                oa = float(ev.group(5))
                
                # Check if already exists
                cursor.execute(
                    'SELECT COUNT(*) FROM matches WHERE season=? AND day=? AND home=? AND away=?',
                    (season_id, md, home, away)
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute('''
                        INSERT INTO matches (season, day, home, away, oh, od, oa, source_file)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (season_id, md, home, away, oh, od, oa, fname))
                    count += 1
    
    conn.commit()
    conn.close()
    return count

def ingest_result_files():
    """Parse all raw result text files and update history.db"""
    count = 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for fname in sorted(os.listdir(RESULTS_DIR)):
        if not fname.endswith('.txt'): continue
        fpath = os.path.join(RESULTS_DIR, fname)
        
        with open(fpath) as f:
            content = f.read()
        
        blocks = re.split(r'={5,}\s*MATCH #\d+ ={5,}', content)
        for block in blocks[1:]:
            season_match = re.search(r'seasonId=vf:season:(\d+)', block)
            if not season_match: continue
            season_id = f"vf:season:{season_match.group(1)}"
            
            md_match = re.search(r'matchDay=(\d+)', block)
            if not md_match: continue
            md = int(md_match.group(1))
            
            # Extract results
            results = re.finditer(
                r'"awayTeam":\s*"([^"]+)".*?'
                r'"homeTeam":\s*"([^"]+)".*?'
                r'"scoreOfWholeMatch":\s*"(\d+):(\d+)"',
                block, re.DOTALL
            )
            
            for res in results:
                away = res.group(1).upper().strip()
                home = res.group(2).upper().strip()
                h = int(res.group(3))
                a = int(res.group(4))
                
                if h > a: outcome = 'HOME'
                elif h < a: outcome = 'AWAY'
                else: outcome = 'DRAW'
                
                # Update existing or insert
                cursor.execute(
                    'SELECT COUNT(*) FROM matches WHERE season=? AND day=? AND home=? AND away=?',
                    (season_id, md, home, away)
                )
                if cursor.fetchone()[0] > 0:
                    cursor.execute('''
                        UPDATE matches SET outcome=?, h=?, a=?, total=?
                        WHERE season=? AND day=? AND home=? AND away=?
                    ''', (outcome, h, a, h+a, season_id, md, home, away))
                else:
                    cursor.execute('''
                        INSERT INTO matches (season, day, home, away, outcome, h, a, total, source_file)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (season_id, md, home, away, outcome, h, a, h+a, fname))
                count += 1
    
    conn.commit()
    conn.close()
    return count

def ingest_h2h_patterns():
    """Load H2H matchup patterns into the bridge-accessible format"""
    if not os.path.exists(H2H_PATH):
        return 0
    
    with open(H2H_PATH) as f:
        h2h = json.load(f)
    
    # Convert to unified intel format
    matchups = h2h if isinstance(h2h, list) else h2h.get('matchups', [])
    
    # Reformat as H2H lookup
    h2h_lookup = {}
    for m in matchups[:100]:  # Top 100 pairings
        if isinstance(m, dict):
            home = m.get('home', '').upper()
            away = m.get('away', '').upper()
            if home and away:
                h2h_lookup[f"{home}_vs_{away}"] = m
    
    # Save as bridge-accessible file
    outpath = os.path.join(BASE, 'analysis/h2h_lookup.json')
    with open(outpath, 'w') as f:
        json.dump(h2h_lookup, f, indent=2)
    
    return len(h2h_lookup)

def main():
    print(f"{'='*60}")
    print(f"📥 VFL DATA INGESTION ENGINE")
    print(f"{'='*60}")
    
    o_count = ingest_odds_files()
    print(f"  Odds files ingested: {o_count} new records")
    
    r_count = ingest_result_files()
    print(f"  Result files ingested: {r_count} records")
    
    h_count = ingest_h2h_patterns()
    print(f"  H2H patterns loaded: {h_count} pairings")
    
    # Verify DB stats
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM matches')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM matches WHERE oh IS NOT NULL')
    with_odds = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM matches WHERE outcome IS NOT NULL')
    with_outcomes = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM matches WHERE oh IS NOT NULL AND outcome IS NOT NULL')
    both = cursor.fetchone()[0]
    conn.close()
    
    print(f"\n📊 Database status:")
    print(f"  Total matches: {total}")
    print(f"  With odds: {with_odds}")
    print(f"  With outcomes: {with_outcomes}")
    print(f"  With BOTH: {both}")
    
    # Refresh the intelligence bridge
    print(f"\n🔄 Refreshing intelligence bridge...")
    os.system(f'python3 {os.path.join(BASE, "scripts/vfl_intelligence_bridge.py")}')
    
    return 0

if __name__ == '__main__':
    exit(main())

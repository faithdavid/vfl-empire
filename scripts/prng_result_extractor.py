#!/usr/bin/env python3
"""MSport Result Extraction Pipeline — Capture outcomes as numeric sequences for PRNG analysis"""
import json, os, sys, time, csv
from datetime import datetime, timezone

sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
os.environ['MSPORT_DEVICE_ID'] = '260524012204pdid09992064'
from msport_api import *

OUTPUT_DIR = '/home/ubuntu/faith-workspace/vfl-data-archive/raw/prng_samples'

def ensure_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def timestamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def extract_goals_sequence():
    """Extract all match results as a flat integer sequence (goals per match)"""
    info = get_current_match_day_info()
    if not info:
        print("FAIL: Could not get current match day info")
        return None
    
    sid = info.get('seasonId')
    sname = info.get('seasonName', '?')
    current_md = info.get('matchDay', 0)
    
    goals_seq = []  # flat: [home_goals, away_goals, home_goals, away_goals, ...]
    scores_seq = []  # formatted: "3-1", "0-0", etc.
    matches_count = 0
    o15_count = 0
    
    # Collect all seasons in reverse (newest first)
    seasons = get_season_list() or []
    season_ids = []
    if seasons:
        # Get current + recent seasons
        if sid:
            season_ids.append(sid)
        # Add up to 5 recent seasons
        for s in seasons:
            sid2 = s.get('seasonId')
            if sid2 and sid2 not in season_ids:
                season_ids.append(sid2)
            if len(season_ids) >= 6:
                break
    
    print(f"Scanning {len(season_ids)} seasons for results...")
    
    for season_id in season_ids[:2]:  # Limit to 2 seasons for speed
        season_name = "?"
        max_md = current_md
        if season_id == sid:
            season_name = sname
        else:
            # Find the max match day for this season
            for s in seasons:
                if s.get('seasonId') == season_id:
                    season_name = s.get('seasonName', '?')
                    mds = s.get('matchDay', [])
                    if mds:
                        max_md = max(mds)
                    break
        
        for md in range(1, max_md + 1):
            results = get_results(season_id, md)
            if not results:
                continue
            for r in results:
                ft = r.get('fullTime', '0:0')
                if ':' not in ft:
                    continue
                hg, ag = map(int, ft.split(':'))
                home = r.get('homeTeam', '?')
                away = r.get('awayTeam', '?')
                goals_seq.extend([hg, ag])
                scores_seq.append(f"{hg}-{ag}")
                matches_count += 1
                if hg + ag >= 2:
                    o15_count += 1
            
            if md % 5 == 0:
                print(f"  {season_name} MD{md}: {len(results)} matches...", end='\r')
    
    print(f"\nCaptured {matches_count} matches across {len(season_ids)} seasons")
    print(f"Goals sequence length: {len(goals_seq)} values")
    print(f"O1.5 rate: {o15_count}/{matches_count} ({o15_count*100//max(matches_count,1)}%)")
    
    return {
        'goals_seq': goals_seq,
        'scores_seq': scores_seq,
        'matches_count': matches_count,
        'o15_count': o15_count,
        'season_name': sname,
        'match_day': current_md,
        'captured_at': timestamp()
    }

def extract_fulltime_results():
    """Extract sequential full-time results as integers for Dieharder/TestU01"""
    info = get_current_match_day_info()
    if not info:
        return None
    
    sid = info.get('seasonId')
    sname = info.get('seasonName', '?')
    md = info.get('matchDay', 0)
    
    # Format: each byte = 2-digit FT result encoded
    # home_goals*10 + away_goals (e.g., 3-1 = 31, 0-0 = 0)
    ft_codes = []
    raw_pairs = []
    
    for m in range(1, md + 1):
        results = get_results(sid, m)
        if not results:
            continue
        for r in results:
            ft = r.get('fullTime', '0:0')
            if ':' not in ft:
                continue
            hg, ag = map(int, ft.split(':'))
            ft_codes.append(hg * 10 + ag)
            raw_pairs.append((hg, ag))
    
    return {
        'ft_codes': ft_codes,
        'raw_pairs': raw_pairs,
        'count': len(ft_codes),
        'season': sname,
        'match_day': md
    }

def save_sample(data, prefix='goals_seq'):
    """Save extracted sequence to file"""
    ensure_dir()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save as JSON
    path_json = f"{OUTPUT_DIR}/{prefix}_{ts}.json"
    with open(path_json, 'w') as f:
        json.dump(data, f, indent=2)
    
    # Save raw numeric sequence (for tools)
    if 'goals_seq' in data:
        path_raw = f"{OUTPUT_DIR}/{prefix}_{ts}.txt"
        with open(path_raw, 'w') as f:
            f.write('\n'.join(str(v) for v in data['goals_seq']))
        path_csv = f"{OUTPUT_DIR}/{prefix}_{ts}.csv"
        with open(path_csv, 'w') as f:
            f.write('home_goals,away_goals,total_goals\n')
            scores = data.get('scores_seq', [])
            seq = data['goals_seq']
            for i in range(0, len(seq), 2):
                if i + 1 < len(seq):
                    f.write(f"{seq[i]},{seq[i+1]},{seq[i]+seq[i+1]}\n")
        
        print(f"Saved: {path_json}")
        print(f"Saved: {path_raw} ({data['matches_count']} matches, {len(data['goals_seq'])} values)")
        print(f"Saved: {path_csv}")
    
    # Save FT codes
    if 'ft_codes' in data:
        path_ft = f"{OUTPUT_DIR}/ft_codes_{ts}.txt"
        with open(path_ft, 'w') as f:
            f.write('\n'.join(str(c) for c in data['ft_codes']))
        print(f"Saved: {path_ft} ({data['count']} FT codes)")
    
    return path_json

def dieharder_test(filepath):
    """Run Dieharder on a raw sequence file if available"""
    print("\n=== DIEHARDER TEST (if installed) ===")
    import subprocess
    try:
        result = subprocess.run(
            ['dieharder', '-a', '-f', filepath, '-g', '202'],
            capture_output=True, text=True, timeout=30
        )
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    except FileNotFoundError:
        print("dieharder not installed. Install: apt install dieharder")
    except subprocess.TimeoutExpired:
        print("dieharder timed out (30s) — expected for large files")
    except Exception as e:
        print(f"dieharder error: {e}")

def test_randcrack(seq):
    """Test RandCrack on goals sequence — detect if it matches MT19937"""
    print("\n=== RANDCRACK TEST ===")
    try:
        from randcrack import RandCrack
        rc = RandCrack()
        
        # Feed the first 624 values (RandCrack needs exactly 624 x 32-bit)
        # Goals are 0-3 range, so pack them
        vals = seq['goals_seq']
        if len(vals) < 1248:  # Need 624 32-bit values = 1248 goals values maximum packed
            print(f"  Insufficient data: {len(vals)} values (need 1248 for full MT19937 state)")
            print(f"  Skipping RandCrack — need more samples")
            return False
        
        # Try packing pairs of 16-bit values
        # Each goal is 0-9 (4 bits), pack 8 goals into one 32-bit value
        packed = []
        for i in range(0, min(len(vals), 4992), 8):
            chunk = vals[i:i+8]
            val = 0
            for j, g in enumerate(chunk):
                val |= (g & 0xF) << (j * 4)
            packed.append(val)
        
        if len(packed) >= 624:
            print(f"  Feeding {624} packed 32-bit values to RandCrack...")
            for v in packed[:624]:
                rc.predict_setrandbits(v, 32)
            future = rc.predict_getrandbits(32)
            print(f"  Future prediction: {future}")
            print(f"  (This only means MT19937 fitting succeeded, NOT that MSport uses MT19937)")
            print(f"  Result: RandCrack accepted the data — but this does NOT prove MSport uses MT19937")
            return True
        else:
            print(f"  Not enough packed values: {len(packed)}/624")
            return False
    except ImportError:
        print("  RandCrack not installed")
    except Exception as e:
        print(f"  Error: {e}")
    return False

def main():
    print("=" * 60)
    print("MSPORT RESULT EXTRACTION PIPELINE")
    print("=" * 60)
    print()
    
    # 1. Extract goals sequence
    print("--- Extracting Goals Sequence ---")
    goals_data = extract_goals_sequence()
    if goals_data:
        path = save_sample(goals_data)
        print()
        
        # 2. Test with RandCrack
        test_randcrack(goals_data)
        
        # 3. Try Dieharder
        raw_txt = path.replace('.json', '.txt')
        dieharder_test(raw_txt)
    
    # 4. Current season deep extraction
    print()
    print("--- Current Season FT Codes ---")
    ft_data = extract_fulltime_results()
    if ft_data:
        save_sample(ft_data, prefix='ft_codes')
        print(f"  FT codes: {ft_data['count']} matches from {ft_data['season']}")
        
        # Compute basic stats
        codes = ft_data['ft_codes']
        if codes:
            avg_total = sum((c // 10) + (c % 10) for c in codes) / len(codes)
            print(f"  Avg goals: {avg_total:.2f}")
            
            # Distribution of outcomes
            dist = {}
            for c in codes:
                hg, ag = divmod(c, 10)
                key = f"{hg}-{ag}"
                dist[key] = dist.get(key, 0) + 1
            print(f"  Top outcomes: {sorted(dist.items(), key=lambda x: -x[1])[:5]}")

if __name__ == '__main__':
    main()

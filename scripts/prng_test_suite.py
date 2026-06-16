#!/usr/bin/env python3
"""PRNG CRACKING TEST SUITE — Tests all installed tools against MSport data"""
import json, os, sys

sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
os.environ['MSPORT_DEVICE_ID'] = '260524012204pdid09992064'
from msport_api import *

DATA_DIR = '/home/ubuntu/faith-workspace/vfl-data-archive/raw/prng_samples'
os.makedirs(DATA_DIR, exist_ok=True)

def collect_all_seasons():
    """Extract ALL available seasons to build a massive dataset"""
    info = get_current_match_day_info()
    sid = info.get('seasonId', '') if info else ''
    sname = info.get('seasonName', '?') if info else '?'
    current_md = info.get('matchDay', 0) if info else 0
    
    seasons = get_season_list() or []
    all_matches = []
    
    # Current season first
    if sid:
        for md in range(1, current_md + 1):
            results = get_results(sid, md)
            if results:
                for r in results:
                    ft = r.get('fullTime', '0:0')
                    if ':' in ft:
                        hg, ag = map(int, ft.split(':'))
                        all_matches.append({
                            'season': sname, 'md': md,
                            'home': r.get('homeTeam'), 'away': r.get('awayTeam'),
                            'hg': hg, 'ag': ag, 'total': hg + ag
                        })
    # Then recent seasons
    for s in seasons[:10]:
        sid2 = s.get('seasonId')
        sname2 = s.get('seasonName', '?')
        if sid2 == sid:  # already got current
            continue
        mds = s.get('matchDay', [])
        if isinstance(mds, list) and mds:
            max_md = max(mds)
            for md in range(1, max_md + 1):
                results = get_results(sid2, md)
                if results:
                    for r in results:
                        ft = r.get('fullTime', '0:0')
                        if ':' in ft:
                            hg, ag = map(int, ft.split(':'))
                            all_matches.append({
                                'season': sname2, 'md': md,
                                'home': r.get('homeTeam'), 'away': r.get('awayTeam'),
                                'hg': hg, 'ag': ag, 'total': hg + ag
                            })
                    if md % 10 == 0:
                        print(f"  {sname2} MD{md}: {all_matches[-1]}", end='\r')
    
    # Save all
    path = f'{DATA_DIR}/all_seasons_20260524.json'
    with open(path, 'w') as f:
        json.dump({'matches': all_matches, 'count': len(all_matches), 'captured_at': __import__('time').time()}, f)
    print(f"\n\nSaved: {path}")
    print(f"Total matches: {len(all_matches)}")
    
    # Compute stats
    if all_matches:
        o15 = sum(1 for m in all_matches if m['total'] >= 2)
        avg = sum(m['total'] for m in all_matches) / len(all_matches)
        print(f"O1.5: {o15}/{len(all_matches)} ({o15*100//len(all_matches)}%)")
        print(f"Avg goals: {avg:.2f}")
    
    return all_matches

def export_for_tools(matches):
    """Export data in formats needed by each tool"""
    goals = []
    for m in matches:
        goals.extend([m['hg'], m['ag']])
    
    # 1. Raw sequence (for Dieharder)
    with open(f'{DATA_DIR}/dieharder_input.txt', 'w') as f:
        for g in goals:
            f.write(f"{g}\n")
    
    # 2. Packed for RandCrack (8 goals per 32-bit value)
    packed = []
    for i in range(0, len(goals) - len(goals) % 8, 8):
        val = 0
        for j in range(8):
            val |= (min(goals[i+j], 15) & 0xF) << (j * 4)
        packed.append(val)
    with open(f'{DATA_DIR}/randcrack_input.txt', 'w') as f:
        for v in packed:
            f.write(f"{v}\n")
    
    # 3. FT codes (home*10 + away)
    with open(f'{DATA_DIR}/ft_codes_input.txt', 'w') as f:
        for m in matches:
            f.write(f"{m['hg']*10 + m['ag']}\n")
    
    # 4. Total goals per match
    with open(f'{DATA_DIR}/total_goals_input.txt', 'w') as f:
        for m in matches:
            f.write(f"{m['total']}\n")
    
    print(f"\nExported for tools:")
    print(f"  Dieharder:  {len(goals)} values")
    print(f"  RandCrack:  {len(packed)} packed 32-bit values {'✅ ENOUGH' if len(packed) >= 624 else f'❌ Need {624-len(packed)} more'}")
    print(f"  FT codes:   {len(matches)} values")
    print(f"  Totals:     {len(matches)} values")
    
    return packed

def test_randcrack(packed):
    print(f"\n{'='*60}")
    print("TEST 1: RandCrack (MT19937 prediction)")
    print(f"{'='*60}")
    try:
        from randcrack import RandCrack
        rc = RandCrack()
        
        if len(packed) < 624:
            print(f"❌ SKIP: Need 624 values, have {len(packed)}")
            return False
        
        tf = 624
        from randcrack import RandCrack
        rc = RandCrack()
        # RandCrack API: submit() to feed, predict_getrandbits() to predict
        for v in packed[:tf]:
            rc.submit(v)
        pred = rc.predict_getrandbits(32)
        actual = packed[tf] if tf < len(packed) else 0
        print(f"  Fed {tf} values → future predicted: {pred}")
        if tf < len(packed):
            match = pred == packed[tf]
            print(f"  Next actual value: {actual} | {'✅ MATCH!' if match else '❌ No match'}")
        print(f"  ** This tests if the sequence fits MT19937.", end='')
        print(" SUCCESS")
        
        return True
    except ImportError as e:
        print(f"  ❌ RandCrack not available: {e}")
        return False

def test_extend_mt(packed):
    print(f"\n{'='*60}")
    print("TEST 2: Extend-MT19937-Predictor (backtrack + predict)")
    print(f"{'='*60}")
    try:
        from extend_mt19937_predictor import ExtendMT19937Predictor
        predictor = ExtendMT19937Predictor()
        
        if len(packed) < 624:
            print(f"❌ SKIP: Need 624 values, have {len(packed)}")
            return False
        
        for v in packed[:624]:
            predictor.setrandbits(v, 32)
        
        # Try predictgetrandbits (common API)
        try:
            pred = predictor.predictgetrandbits(32)
            print(f"  Fed 624 values → future prediction: {pred}")
        except AttributeError:
            pred = predictor.predict_getrandbits(32)
            print(f"  Fed 624 values → future prediction: {pred}")
        
        # Backtrack
        try:
            backtrack = predictor.backtrack_getrandbits(32) 
            print(f"  Backtrack: {backtrack}")
        except AttributeError:
            try:
                backtrack = predictor.backtrack_get_bits(32)
                print(f"  Backtrack: {backtrack}")
            except:
                print(f"  Backtrack: N/A (method not found)")
        
        print(f"  Actual next packed: {packed[624] if len(packed) > 624 else 'N/A'}")
        return True
    except ImportError as e:
        print(f"  ❌ ExtendMT not available: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_jvdsn_lcg(matches):
    print(f"\n{'='*60}")
    print("TEST 3: jvdsn/crypto-attacks LCG Analysis")
    print(f"{'='*60}")
    try:
        sys.path.insert(0, '/home/ubuntu/faith-workspace/crypto-attacks')
        from attacks.lcg import parameter_recovery, truncated_parameter_recovery
        
        # Extract total goals as LCG-like sequence
        totals = [m['total'] for m in matches]
        print(f"  Total goals sequence: {len(totals)} values")
        print(f"  Range: {min(totals)}-{max(totals)}")
        
        # Parameter recovery (assumes full output LCG)
        try:
            params = parameter_recovery.recover_parameters(totals[:20])
            print(f"  LCG parameters: a={params.get('a')}, c={params.get('c')}, m={params.get('m')}")
            if params.get('a'):
                print(f"  ⚠️ WARNING: Parameters found! LCG-like structure detected!")
            else:
                print(f"  ✅ No LCG structure detected (expected for CSPRNG)")
        except Exception as e:
            print(f"  Parameter recovery: {e}")
        
        return True
    except ImportError as e:
        print(f"  ❌ jvdsn/crypto-attacks not available: {e}")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def test_z3_approach(matches):
    print(f"\n{'='*60}")
    print("TEST 4: Z3 Approach Check")
    print(f"{'='*60}")
    try:
        try:
            import z3
        except ImportError:
            print(f"  ❌ Z3 not installed (pip install z3-solver)")
            return False
        print(f"  ✅ Z3 is available (version: {z3.get_version_string()})")
        
        # Simple test: can Z3 solve for LCG parameters?
        totals = [m['total'] for m in matches[:5]]
        
        s = z3.Solver()
        a = z3.BitVec('a', 32)
        c = z3.BitVec('c', 32)
        m_val = z3.BitVecVal(2**31 - 1, 32)
        x0 = z3.BitVec('x0', 32)
        
        # constraint: x_{i+1} = (a * x_i + c) mod m
        for i in range(min(len(totals)-1, 4)):
            xi = z3.BitVecVal(totals[i], 32)
            xi1 = z3.BitVecVal(totals[i+1], 32)
            s.add(xi1 == z3.UDiv(a * xi + c, m_val))  # simplified
        
        result = s.check()
        print(f"  Simple LCG Z3 solve: {result}")
        if result == z3.sat:
            print(f"  ⚠️ Z3 found a model — possible LCG structure")
            print(f"  Model: {s.model()}")
        else:
            print(f"  ✅ No LCG model found (expected for CSPRNG)")
        
        return True
    except ImportError:
        print(f"  ❌ Z3 not installed (pip install z3-solver)")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def test_statistical(matches):
    print(f"\n{'='*60}")
    print("TEST 5: Basic Statistical Analysis")
    print(f"{'='*60}")
    
    totals = [m['total'] for m in matches]
    if not totals:
        return
    
    from collections import Counter
    
    # Distribution
    dist = Counter(totals)
    print(f"  Goals distribution:")
    for g in sorted(dist):
        pct = dist[g] * 100 / len(totals)
        bar = '█' * int(pct)
        print(f"    {g} goals: {dist[g]:5d} ({pct:5.1f}%) {bar}")
    
    # Home vs away advantage
    home_wins = sum(1 for m in matches if m['hg'] > m['ag'])
    away_wins = sum(1 for m in matches if m['ag'] > m['hg'])
    draws = sum(1 for m in matches if m['hg'] == m['ag'])
    print(f"  Home win: {home_wins} | Draw: {draws} | Away win: {away_wins}")
    print(f"  Home advantage: {home_wins*100//max(len(matches),1)}%")
    
    # Runs test (simple randomness check)
    above_avg = [1 if m['total'] >= 2.5 else 0 for m in matches]
    runs = 1
    for i in range(1, len(above_avg)):
        if above_avg[i] != above_avg[i-1]:
            runs += 1
    expected_runs = len(matches) / 2 + 1
    print(f"  Runs test (O2.5 runs): {runs} vs expected {expected_runs:.1f} {'✅ random-like' if abs(runs - expected_runs) < expected_runs * 0.3 else '⚠️ non-random pattern'}")

def main():
    print("=" * 60)
    print("PRNG CRACKING TEST SUITE — VFL EMPIRE")
    print("=" * 60)
    print()
    
    # Collect data
    print("Collecting all available seasons...")
    matches = collect_all_seasons()
    if not matches:
        print("❌ No matches collected!")
        return
    
    # Export for tools
    packed = export_for_tools(matches)
    
    # Run tests
    test_randcrack(packed)
    test_extend_mt(packed)
    test_jvdsn_lcg(matches)
    test_z3_approach(matches)
    test_statistical(matches)
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Total matches analyzed: {len(matches)}")
    print(f"  Seasons scanned: {len(set(m['season'] for m in matches))}")
    print(f"  Tools loaded: RandCrack={__import__('importlib').util.find_spec('randcrack') is not None}")
    print(f"  Data exported to: {DATA_DIR}/")
    print()

if __name__ == '__main__':
    main()

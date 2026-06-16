#!/usr/bin/env python3
"""Continuous MSport result capture — accumulates data for PRNG analysis"""
import json, os, sys, time
from datetime import datetime, timezone

sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
os.environ['MSPORT_DEVICE_ID'] = '260524012204pdid09992064'
from msport_api import *

OUTPUT_DIR = '/home/ubuntu/faith-workspace/vfl-data-archive/raw/prng_samples'
ACCUM_FILE = f'{OUTPUT_DIR}/accumulated_results.json'

def load_accumulated():
    if os.path.exists(ACCUM_FILE):
        with open(ACCUM_FILE) as f:
            return json.load(f)
    return {'matches': [], 'seasons': {}, 'last_season_id': None, 'last_match_day': 0}

def save_accumulated(data):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(ACCUM_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def extract_and_accumulate():
    acc = load_accumulated()
    seen = set((m['season_id'], m['match_day'], m['home'], m['away']) for m in acc['matches'])
    
    info = get_current_match_day_info()
    if not info:
        return acc
    
    sid = info.get('seasonId')
    sname = info.get('seasonName', '?')
    current_md = info.get('matchDay', 0)
    
    new_count = 0
    for md in range(1, current_md + 1):
        results = get_results(sid, md)
        if not results:
            continue
        for r in results:
            key = (sid, md, r.get('homeTeam'), r.get('awayTeam'))
            if key not in seen:
                seen.add(key)
                ft = r.get('fullTime', '0:0')
                if ':' in ft:
                    hg, ag = map(int, ft.split(':'))
                    acc['matches'].append({
                        'season_id': sid,
                        'season_name': sname,
                        'match_day': md,
                        'home': r.get('homeTeam'),
                        'away': r.get('awayTeam'),
                        'home_goals': hg,
                        'away_goals': ag,
                        'total_goals': hg + ag,
                        'captured_at': datetime.now(timezone.utc).isoformat()
                    })
                    new_count += 1
    
    acc['last_season_id'] = sid
    acc['last_match_day'] = current_md
    acc['seasons'][sname] = current_md
    save_accumulated(acc)
    
    # Export as raw numeric sequences for tools
    goals = []
    for m in acc['matches']:
        goals.extend([m['home_goals'], m['away_goals']])
    
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    with open(f'{OUTPUT_DIR}/goals_sequence.txt', 'w') as f:
        f.write('\n'.join(str(v) for v in goals))
    
    # Pack for RandCrack (pack 8 goals into 32 bits)
    packed = []
    for i in range(0, len(goals) - len(goals) % 8, 8):
        val = 0
        for j in range(8):
            val |= (goals[i+j] & 0xF) << (j * 4)
        packed.append(val)
    with open(f'{OUTPUT_DIR}/randcrack_input.txt', 'w') as f:
        f.write('\n'.join(str(v) for v in packed))
    
    print(f"Total: {len(acc['matches'])} matches, {len(goals)} goals, {len(packed)} packed vals")
    print(f"New this run: {new_count}")
    print(f"RandCrack ready: {'YES' if len(packed) >= 624 else f'NEED {624 - len(packed)} more'}")
    
    return acc

if __name__ == '__main__':
    result = extract_and_accumulate()
    print(f"\nSeasons: {list(result['seasons'].keys())}")

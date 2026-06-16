import json
import glob
import os

path = '/home/ubuntu/faith-workspace/vfl-empire/network-capture/*/*.ndjson'
files = glob.glob(path)
latest_file = max(files, key=os.path.getmtime)

matches = {}
with open(latest_file, 'r') as f:
    for line in f:
        try:
            data = json.loads(line)
            # Find elements that contain homeTeam and awayTeam
            payload_str = json.dumps(data)
            if 'homeTeam' in payload_str:
                if 'payload' in data and isinstance(data['payload'], dict) and 'data' in data['payload']:
                    payload_data = data['payload']['data']
                    if 'fixtures' in payload_data:
                        for fix in payload_data['fixtures']:
                            s = fix.get('seasonId')
                            d = fix.get('matchDay')
                            h = fix.get('homeTeam', {}).get('name')
                            a = fix.get('awayTeam', {}).get('name')
                            if s and d and h and a:
                                if s not in matches: matches[s] = {}
                                if d not in matches[s]: matches[s][d] = []
                                matches[s][d].append((h, a))
        except:
            pass

# Get the latest season and day from the dictionary
if matches:
    latest_season = max(matches.keys())
    latest_day = max(matches[latest_season].keys())
    print(f"Season: {latest_season}, Matchday: {latest_day}")
    # unique matches only
    unique_matches = list(set(matches[latest_season][latest_day]))
    for h, a in unique_matches:
        print(f"{h} vs {a}")
else:
    print("No fixtures found.")

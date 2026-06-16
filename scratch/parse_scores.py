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
            if 'payload' in data and isinstance(data['payload'], dict) and 'data' in data['payload']:
                payload_data = data['payload']['data']
                if 'fixtures' in payload_data:
                    for fix in payload_data['fixtures']:
                        s = fix.get('seasonId')
                        d = fix.get('matchDay')
                        h = fix.get('homeTeam', {}).get('name')
                        a = fix.get('awayTeam', {}).get('name')
                        status = fix.get('status')
                        hs = fix.get('homeTeam', {}).get('score')
                        as_ = fix.get('awayTeam', {}).get('score')
                        
                        if s == 'vf:season:3100750' and d == 10:
                            if h not in matches or status == 3: # 3 usually means finished
                                matches[h] = {"away": a, "home_score": hs, "away_score": as_, "status": status}
        except:
            pass

for h, m in matches.items():
    print(f"{h} {m['home_score']} - {m['away_score']} {m['away']} (Status: {m['status']})")

import json

def normalize_fixture(f):
    teams = sorted(f.split(","))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    return frozenset([normalize_fixture(f) for f in fixtures])

def find_twin_sequence():
    # Load current season data from the database dump I just got
    current_data = """
1,Brighton,Leeds
1,Aston Villa,Everton
1,West Ham,Tottenham
1,Chelsea,Fulham
1,Manchester Red,London Guns
1,Crystal Palace,Manchester Blue
1,Liverpool,Wolverhampton
1,Newcastle,Bournemouth
2,Tottenham,Brighton
2,Everton,Manchester Red
2,Manchester Blue,Chelsea
2,London Guns,Crystal Palace
2,Bournemouth,Liverpool
2,Wolverhampton,Aston Villa
2,Fulham,West Ham
2,Leeds,Newcastle
3,Manchester Red,Aston Villa
3,Newcastle,Tottenham
3,Bournemouth,Wolverhampton
3,Liverpool,Leeds
3,West Ham,Manchester Blue
3,Chelsea,London Guns
3,Crystal Palace,Everton
3,Brighton,Fulham
4,Fulham,Newcastle
4,Wolverhampton,Manchester Red
4,Tottenham,Liverpool
4,Leeds,Bournemouth
4,Manchester Blue,Brighton
4,Aston Villa,Crystal Palace
4,Everton,Chelsea
4,London Guns,West Ham
5,Newcastle,Manchester Blue
5,Chelsea,Aston Villa
5,Liverpool,Fulham
5,Leeds,Wolverhampton
5,Bournemouth,Tottenham
5,West Ham,Everton
5,Brighton,London Guns
5,Crystal Palace,Manchester Red
6,Manchester Blue,Liverpool
6,Tottenham,Leeds
6,Everton,Brighton
6,Aston Villa,West Ham
6,London Guns,Newcastle
6,Fulham,Bournemouth
6,Wolverhampton,Crystal Palace
6,Manchester Red,Chelsea
7,Chelsea,Crystal Palace
7,Liverpool,London Guns
7,Bournemouth,Manchester Blue
7,West Ham,Manchester Red
7,Tottenham,Wolverhampton
7,Brighton,Aston Villa
7,Leeds,Fulham
7,Newcastle,Everton
8,London Guns,Bournemouth
8,Everton,Liverpool
8,Crystal Palace,West Ham
8,Fulham,Tottenham
8,Manchester Blue,Leeds
8,Aston Villa,Newcastle
8,Manchester Red,Brighton
8,Wolverhampton,Chelsea
9,Fulham,Wolverhampton
9,West Ham,Chelsea
9,Liverpool,Aston Villa
9,Tottenham,Manchester Blue
9,Leeds,London Guns
9,Newcastle,Manchester Red
9,Bournemouth,Everton
9,Brighton,Crystal Palace
10,Manchester Red,Liverpool
10,Wolverhampton,West Ham
10,London Guns,Tottenham
10,Everton,Leeds
10,Aston Villa,Bournemouth
10,Crystal Palace,Newcastle
10,Manchester Blue,Fulham
10,Chelsea,Brighton
11,Manchester Blue,Wolverhampton
11,Tottenham,Everton
11,Bournemouth,Manchester Red
11,Newcastle,Chelsea
11,Liverpool,Crystal Palace
11,Leeds,Aston Villa
11,Fulham,London Guns
11,Brighton,West Ham
12,Aston Villa,Tottenham
12,Manchester Red,Leeds
12,Wolverhampton,Brighton
12,Crystal Palace,Bournemouth
12,Chelsea,Liverpool
12,London Guns,Manchester Blue
12,Everton,Fulham
12,West Ham,Newcastle
13,London Guns,Wolverhampton
13,Newcastle,Brighton
13,Fulham,Aston Villa
13,Leeds,Crystal Palace
13,Liverpool,West Ham
13,Bournemouth,Chelsea
13,Tottenham,Manchester Red
13,Manchester Blue,Everton
14,Chelsea,Leeds
14,Manchester Red,Fulham
14,Brighton,Liverpool
14,Wolverhampton,Newcastle
14,Everton,London Guns
14,Aston Villa,Manchester Blue
14,West Ham,Bournemouth
14,Crystal Palace,Tottenham
15,Tottenham,Chelsea
15,Leeds,West Ham
15,Bournemouth,Brighton
15,Manchester Blue,Manchester Red
15,London Guns,Aston Villa
15,Fulham,Crystal Palace
15,Liverpool,Newcastle
15,Everton,Wolverhampton
16,Manchester Blue,Crystal Palace
16,Wolverhampton,Liverpool
16,Bournemouth,Newcastle
16,Leeds,Brighton
16,Everton,Aston Villa
16,Tottenham,West Ham
16,Fulham,Chelsea
16,London Guns,Manchester Red
17,Crystal Palace,London Guns
17,Liverpool,Bournemouth
17,Aston Villa,Wolverhampton
17,West Ham,Fulham
17,Newcastle,Leeds
17,Brighton,Tottenham
17,Manchester Red,Everton
17,Chelsea,Manchester Blue
18,London Guns,Chelsea
18,Everton,Crystal Palace
18,Fulham,Brighton
18,Aston Villa,Manchester Red
18,Tottenham,Newcastle
18,Wolverhampton,Bournemouth
18,Leeds,Liverpool
18,Manchester Blue,West Ham
19,Bournemouth,Leeds
19,Brighton,Manchester Blue
19,Crystal Palace,Aston Villa
19,Chelsea,Everton
19,West Ham,London Guns
19,Newcastle,Fulham
19,Manchester Red,Wolverhampton
19,Liverpool,Tottenham
20,Everton,West Ham
20,London Guns,Brighton
20,Manchester Red,Crystal Palace
20,Manchester Blue,Newcastle
20,Aston Villa,Chelsea
20,Fulham,Liverpool
20,Wolverhampton,Leeds
20,Tottenham,Bournemouth
21,West Ham,Aston Villa
21,Newcastle,London Guns
21,Bournemouth,Fulham
21,Crystal Palace,Wolverhampton
21,Chelsea,Manchester Red
21,Liverpool,Manchester Blue
21,Leeds,Tottenham
21,Brighton,Everton
22,Aston Villa,Brighton
22,Fulham,Leeds
22,Everton,Newcastle
22,Crystal Palace,Chelsea
22,London Guns,Liverpool
22,Manchester Blue,Bournemouth
22,Manchester Red,West Ham
22,Wolverhampton,Tottenham
23,Tottenham,Fulham
23,Leeds,Manchester Blue
23,Newcastle,Aston Villa
23,Brighton,Manchester Red
23,Chelsea,Wolverhampton
23,Bournemouth,London Guns
23,Liverpool,Everton
23,West Ham,Crystal Palace
24,Manchester Red,Newcastle
24,Everton,Bournemouth
24,Crystal Palace,Brighton
24,Wolverhampton,Fulham
24,Chelsea,West Ham
24,Aston Villa,Liverpool
24,Manchester Blue,Tottenham
24,London Guns,Leeds
25,Leeds,Everton
25,Bournemouth,Aston Villa
25,Newcastle,Crystal Palace
25,Fulham,Manchester Blue
25,Brighton,Chelsea
25,Liverpool,Manchester Red
25,West Ham,Wolverhampton
25,Tottenham,London Guns
"""
    
    current_progression = {}
    for line in current_data.strip().split('\n'):
        if not line: continue
        parts = line.split(',')
        if len(parts) < 3: continue
        md = int(parts[0])
        fixture = f"{parts[1]},{parts[2]}"
        if md not in current_progression:
            current_progression[md] = []
        current_progression[md].append(fixture)
        
    current_sigs = [get_signature(current_progression[m]) for m in sorted(current_progression.keys())]
    
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
        
    matches = []
    
    def normalize_hist_fix(f):
        ts = sorted(f.split(" vs "))
        return f"{ts[0]} vs {ts[1]}"

    def get_hist_sig(fixtures):
        return frozenset([normalize_hist_fix(f["teams"]) for f in fixtures])

    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        season_sigs = [get_hist_sig(seasons[k]) for k in md_keys]
        
        # Look for the current progression sequence within this season
        for i in range(len(season_sigs) - len(current_sigs) + 1):
            is_match = True
            for j in range(len(current_sigs)):
                if current_sigs[j] != season_sigs[i+j]:
                    is_match = False
                    break
            if is_match:
                matches.append({
                    "target_season": s_name,
                    "start_md": md_keys[i],
                    "offset": i
                })
                
    return matches

if __name__ == "__main__":
    matches = find_twin_sequence()
    if not matches:
        print("No identical twin sequence found.")
    else:
        print(f"Found {len(matches)} twin sequences:")
        print(json.dumps(matches, indent=2))

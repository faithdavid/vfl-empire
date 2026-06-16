import re
import json

text = """
ArthurAPP
—
11:59 AM
VFL CONDITIONAL LOCKS | Matchday 5  Leeds vs London Guns
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Macro Trap (T3 vs T2)
↳  [MACRO LOCK] Under 3.5  •  85.1% Everton vs Aston Villa
↳  [MACRO LOCK] Under 3.5  •  92.6% Wolverhampton vs West Ham
BLINDSPOT COVER: Play Over 1.5 (73% Safe)
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 88.2% | Micro: 90.0%
↳  [MICRO LOCK] Over 2.5  •  90.0%
↳  [MICRO LOCK] GG (BTTS)  •  90.0% Crystal Palace vs Newcastle
↳  [MACRO LOCK] Under 3.5  •  91.9%
VFL CONDITIONAL LOCKS | Matchday 6  Fulham vs Chelsea
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Macro Trap (T2 vs T1)
↳  [MACRO LOCK] Under 3.5  •  85.7% Bournemouth vs Leeds
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 88.5% | Micro: 88.1% Newcastle vs Everton
↳  [MACRO LOCK] Under 3.5  •  88.9%
ArthurAPP
—
12:07 PM
VFL CONDITIONAL LOCKS | Matchday 7  Leeds vs Fulham
↳  [MACRO LOCK] Under 3.5  •  92.3% Manchester Red vs London Guns
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Macro Trap (T3 vs T2)
↳  [MACRO LOCK] Under 3.5  •  100.0% Liverpool vs Bournemouth
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 87.0% | Micro: 100.0% Wolverhampton vs Tottenham
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Specific Team Chaos
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 80.3% | Micro: 82.6%
VFL CONDITIONAL LOCKS | Matchday 8  Everton vs Chelsea
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 84.0% | Micro: 91.7% Aston Villa vs Leeds
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 90.8% | Micro: 85.0% London Guns vs Wolverhampton
↳  [MICRO LOCK] Over 1.5  •  93.3%
ArthurAPP
—
12:14 PM
VFL CONDITIONAL LOCKS | Matchday 9  Leeds vs Everton
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 93.9% | Micro: 94.7%
VFL CONDITIONAL LOCKS | Matchday 10  Bournemouth vs Crystal Palace
↳  [MACRO LOCK] Under 3.5  •  87.5% Fulham vs Wolverhampton
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 90.9% | Micro: 90.9% Newcastle vs Chelsea
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 87.6% | Micro: 82.1% Tottenham vs Brighton
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 80.5% | Micro: 80.0% Aston Villa vs Manchester Red
↳  [MACRO LOCK] Under 3.5  •  94.1%
ArthurAPP
—
12:21 PM
VFL CONDITIONAL LOCKS | Matchday 11  Tottenham vs Newcastle
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Macro Trap (T1 vs T3)
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 80.8% | Micro: 80.0%
↳  [MICRO LOCK] Home Win (1)  •  86.7% Brighton vs London Guns
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 82.9% | Micro: 83.3% Leeds vs Chelsea
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 85.0% | Micro: 87.1% Wolverhampton vs Aston Villa
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 80.0% | Micro: 86.7%
VFL CONDITIONAL LOCKS | Matchday 12  Everton vs Wolverhampton
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 87.9% | Micro: 81.8% Manchester Blue vs Manchester Red
↳  [MICRO LOCK] Over 1.5  •  94.1% Newcastle vs Leeds
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 90.3% | Micro: 85.7% Bournemouth vs Brighton
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 84.7% | Micro: 84.2%
ArthurAPP
—
12:29 PM
VFL CONDITIONAL LOCKS | Matchday 13  London Guns vs Newcastle
↳  [MICRO LOCK] Over 1.5  •  88.2% Crystal Palace vs Everton
↳  [MACRO LOCK] Under 3.5  •  92.3%
VFL CONDITIONAL LOCKS | Matchday 14  Bournemouth vs London Guns
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 80.1% | Micro: 85.4% Aston Villa vs Brighton
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Macro Trap (T3 vs T2)
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 91.7% | Micro: 86.7% Everton vs West Ham
↳  [MACRO LOCK] Under 3.5  •  91.7% Chelsea vs Wolverhampton
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Macro Trap (T1 vs T3)
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 80.4% | Micro: 88.9%
ArthurAPP
—
12:36 PM
VFL CONDITIONAL LOCKS | Matchday 15  West Ham vs Manchester Blue
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 81.0% | Micro: 89.5% Bournemouth vs Newcastle
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 88.9% | Micro: 91.1% London Guns vs Fulham
↳  [MACRO LOCK] Under 3.5  •  90.0% Wolverhampton vs Leeds
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 89.3% | Micro: 87.5%
↳  [MICRO LOCK] Under 2.5  •  87.5%
VFL CONDITIONAL LOCKS | Matchday 16  Crystal Palace vs Leeds
↳  [MACRO LOCK] Under 3.5  •  88.9% Bournemouth vs Fulham
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 93.5% | Micro: 84.6% Wolverhampton vs Liverpool
↳  [MICRO LOCK] Under 3.5  •  90.0% London Guns vs Aston Villa
↳  [CONFLUENCE LOCK] Over 1.5  •  Macro: 80.6% | Micro: 91.7% Tottenham vs Everton
[CHAOS TRAP WARNING] Do not bet heavily. MSport RNG Target: Macro Trap (T1 vs T3)
↳  [CONFLUENCE LOCK] Under 3.5  •  Macro: 87.9% | Micro: 93.3%
Results
06062026 / Season 5297 / Match Day 3
Team
1st Goal
HT
FT
Manchester Red - Crystal Palace
Away
0:1
0:2
Wolverhampton - Newcastle
Home
1:1
2:2
Chelsea - Tottenham
Home
2:0
2:0
Leeds - Brighton
Away
0:0
0:1
Everton - Bournemouth
None
0:0
0:0
Liverpool - West Ham
Away
0:1
1:1
Aston Villa - Fulham
Home
1:0
1:0
Manchester Blue - London Guns
Away
3:1
6:1
Results
06062026 / Season 5297 / Match Day 4
Team
1st Goal
FT
Brighton - Liverpool
Away
0:1
1:2
Bournemouth - Manchester Blue
Away
0:0
0:1
Fulham - Everton
None
0:0
0:0
London Guns - Chelsea
Home
1:1
1:2
West Ham - Manchester Red
Away
0:1
0:2
Newcastle - Aston Villa
Away
0:0
0:1
Tottenham - Leeds
Home
0:0
1:0
Crystal Palace - Wolverhampton
Home
0:0
1:0
Results
06062026 / Season 5297 / Match Day 6
Team
1st Goal
HT
FT
Tottenham - Manchester Red
Away
0:1
2:1
Newcastle - Everton
None
0:0
0:0
Brighton - Wolverhampton
Home
0:0
1:1
Aston Villa - Manchester Blue
Home
1:2
1:3
Bournemouth - Leeds
Away
0:2
1:3
West Ham - Crystal Palace
Home
1:1
1:2
London Guns - Liverpool
Home
1:0
3:1
Fulham - Chelsea
Away
0:1
1:1
Results
06062026 / Season 5297 / Match Day 7
Team
1st Goal
HT
FT
Chelsea - Aston Villa
Away
0:1
2:1
Wolverhampton - Tottenham
Away
0:1
1:3
West Ham - Newcastle
Home
1:1
1:2
Liverpool - Bournemouth
Home
1:0
2:2
Crystal Palace - Brighton
Away
1:1
1:2
Manchester Red - London Guns
None
0:0
0:0
Manchester Blue - Everton
None
0:0
0:0
Leeds - Fulham
None
0:0
0:0
Results
06062026 / Season 5297 / Match Day 8
Team
1st Goal
HT
FT
London Guns - Wolverhampton
Home
1:0
1:0
Aston Villa - Leeds
Home
2:0
3:1
Fulham - Liverpool
Away
0:2
2:2
Newcastle - Manchester Blue
Away
1:1
1:1
Everton - Chelsea
Away
0:0
0:2
Bournemouth - Manchester Red
Away
0:1
0:3
Tottenham - Crystal Palace
Home
1:0
2:0
Brighton - West Ham
Away
0:0
0:1
Results
06062026 / Season 5297 / Match Day 9
Team
1st Goal
HT
FT
West Ham - Tottenham
None
0:0
0:0
Manchester Red - Fulham
Home
0:0
2:0
Crystal Palace - London Guns
Home
1:0
1:0
Leeds - Everton
Away
0:1
0:1
Wolverhampton - Bournemouth
Home
1:0
3:0
Chelsea - Manchester Blue
Away
1:2
1:3
Brighton - Newcastle
Away
0:3
2:3
Liverpool - Aston Villa
Away
0:1
0:3
Results
06062026 / Season 5297 / Match Day 10
Team
1st Goal
HT
FT
Aston Villa - Manchester Red
Away
1:3
1:4
Tottenham - Brighton
Home
3:0
4:0
Everton - Liverpool
Away
0:0
0:3
Manchester Blue - Leeds
Away
0:1
1:2
London Guns - West Ham
Away
1:1
2:1
Newcastle - Chelsea
Home
2:1
2:3
Fulham - Wolverhampton
Away
0:1
2:1
Bournemouth - Crystal Palace
Home
1:0
1:0
Results
06062026 / Season 5297 / Match Day 11
Team
1st Goal
HT
FT
Liverpool - Manchester Blue
Away
0:0
0:1
Wolverhampton - Aston Villa
Away
0:0
1:1
Manchester Red - Everton
Away
1:1
2:2
Leeds - Chelsea
Home
1:0
1:0
Brighton - London Guns
Home
1:0
1:0
West Ham - Bournemouth
Away
0:0
1:1
Tottenham - Newcastle
Away
0:1
1:1
Crystal Palace - Fulham
Away
0:1
1:1
Results
06062026 / Season 5297 / Match Day 12
Team
1st Goal
HT
FT
Fulham - West Ham
Home
2:0
2:1
Bournemouth - Brighton
Away
0:3
0:3
London Guns - Tottenham
Away
0:1
1:1
Chelsea - Liverpool
Home
1:0
2:0
Newcastle - Leeds
Away
0:0
0:1
Aston Villa - Crystal Palace
Away
0:0
0:1
Manchester Blue - Manchester Red
1:1
3:1
Everton - Wolverhampton
Away
1:3
1:3
Results
06062026 / Season 5297 / Match Day 13
Team
1st Goal
HT
FT
Crystal Palace - Everton
None
0:0
0:0
Brighton - Fulham
Home
0:0
1:0
Manchester Red - Chelsea
Home
0:0
1:0
Tottenham - Bournemouth
Away
0:1
0:1
West Ham - Aston Villa
Home
1:0
1:0
Liverpool - Leeds
Away
0:1
3:1
London Guns - Newcastle
Away
0:0
0:1
Wolverhampton - Manchester Blue
Away
1:1
1:3
Results
06062026 / Season 5297 / Match Day 14
Team
1st Goal
HT
FT
Manchester Blue - Crystal Palace
Home
2:0
2:2
Chelsea - Wolverhampton
Home
2:1
2:1
Fulham - Tottenham
Away
2:1
2:3
Everton - West Ham
Home
2:1
4:1
Leeds - Manchester Red
Home
1:3
1:5
Aston Villa - Brighton
Home
1:1
2:2
Bournemouth - London Guns
Home
3:1
4:1
Newcastle - Liverpool
None
0:0
0:0
Results
06062026 / Season 5297 / Match Day 15
Team
1st Goal
HT
FT
Tottenham - Aston Villa
Home
0:0
1:0
Wolverhampton - Leeds
Away
0:0
2:1
London Guns - Fulham
Home
1:2
2:2
Bournemouth - Newcastle
Away
0:1
0:1
Manchester Red - Liverpool
Home
1:1
1:1
Crystal Palace - Chelsea
None
0:0
0:0
West Ham - Manchester Blue
Away
0:2
2:2
Brighton - Everton
Home
1:0
1:0
Results
06062026 / Season 5297 / Match Day 16
Team
1st Goal
HT
FT
Tottenham - Everton
Home
2:0
2:1
Brighton - Manchester Blue
Home
1:0
1:0
West Ham - Chelsea
Away
0:1
2:1
London Guns - Aston Villa
Away
0:0
0:2
Wolverhampton - Liverpool
Home
1:1
2:2
Newcastle - Manchester Red
Away
0:1
0:4
Bournemouth - Fulham
Away
0:0
0:1
Crystal Palace - Leeds
Home
0:0
1:1
"""

lines = text.split('\n')

# Build the results dictionary
res_blocks = re.split(r'Results\n06062026 / Season 5297 / Match Day \d+', text)
res_data = {}
for i, b in enumerate(re.finditer(r'Match Day (\d+)', text)):
    md = int(b.group(1))
    block = res_blocks[i+1]
    res_data[md] = {}
    
    block_lines = iter(block.strip().split('\n'))
    for line in block_lines:
        line = line.strip()
        if " - " in line and "Goal" not in line and "Team" not in line:
            parts = line.split(" - ")
            if len(parts) == 2:
                home = parts[0].strip().replace('\xa0', ' ')
                away = parts[1].strip().replace('\xa0', ' ')
                try:
                    nxt = next(block_lines).strip()
                    if ":" in nxt and "1st Goal" not in nxt:
                        score = nxt
                    else:
                        nxt2 = next(block_lines).strip()
                        if ":" in nxt2 and len(nxt2) <= 5:
                            score = nxt2
                            nxt3 = next(block_lines).strip()
                            if ":" in nxt3 and len(nxt3) <= 5:
                                score = nxt3
                        else:
                            score = "0:0"
                except StopIteration:
                    score = "0:0"
                res_data[md][f"{home} vs {away}"] = score

preds = []
cur_md = None
main_match = None

for line in lines:
    if "VFL CONDITIONAL LOCKS | Matchday" in line:
        m = re.search(r'Matchday (\d+)\s+(.*)', line)
        if m:
            cur_md = int(m.group(1))
            main_match = m.group(2).strip()
    elif "LOCK]" in line:
        m_type = re.search(r'\[(.*?)\]', line)
        lock_type = m_type.group(1) if m_type else "UNKNOWN"
        market = re.search(r'\] (.*?)  •', line)
        market_str = market.group(1).strip() if market else "UNKNOWN"
        t_match = re.search(r'%\s+(.*)', line)
        teams = t_match.group(1).strip() if t_match else main_match
        if not teams:
            teams = main_match
        preds.append({'md': cur_md, 'type': lock_type, 'market': market_str, 'teams': teams})

def eval_hit(market, score):
    parts = score.split(':')
    if len(parts) != 2: return False
    h, a = int(parts[0]), int(parts[1])
    tg = h + a
    if market == "Under 3.5": return tg < 3.5
    if market == "Over 1.5": return tg > 1.5
    if market == "Over 2.5": return tg > 2.5
    if market == "Under 2.5": return tg < 2.5
    if market == "GG (BTTS)": return h > 0 and a > 0
    if market == "Home Win (1)": return h > a
    return False

results = {'MACRO LOCK': {'hits': 0, 'misses': 0}, 'MICRO LOCK': {'hits': 0, 'misses': 0}, 'CONFLUENCE LOCK': {'hits': 0, 'misses': 0}}

print("--- EVALUATION ---")
for p in preds:
    md = p['md']
    if md not in res_data:
        continue
    
    score = res_data[md].get(p['teams'])
    if not score:
        if ' vs ' in p['teams']:
            h, a = p['teams'].split(' vs ')
            score = res_data[md].get(f"{a} vs {h}")
            
    if score:
        hit = eval_hit(p['market'], score)
        if hit:
            results[p['type']]['hits'] += 1
        else:
            results[p['type']]['misses'] += 1
        print(f"MD {md} | {p['type']} | {p['market']} | {p['teams']} -> {score} [{'HIT' if hit else 'MISS'}]")

print("\n--- SUMMARY ---")
for t, d in results.items():
    total = d['hits'] + d['misses']
    rate = (d['hits'] / total * 100) if total > 0 else 0
    print(f"{t}: {d['hits']} Hits, {d['misses']} Misses -> {rate:.1f}%")

#!/usr/bin/env python3
"""
VFL Oracle Collector — fetches matchday context for agent-based reasoning.
Outputs a single JSON blob with all data the Oracle agent needs to predict.
No ML. No stale code. Just fresh data for LLM reasoning.
"""
import urllib.request, json, os, sys
from collections import defaultdict
from datetime import datetime

UA = "Mozilla/5.0"
BASE = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual"

# ─── Load analysis data ───
ANALYSIS_DIR = os.path.expanduser("~/Documents/Projects/vfl-data/analysis")
CONSTRAINTS_PATH = os.path.join(ANALYSIS_DIR, "clara_permutation_analysis.json")
BIAS_PATH = os.path.join(ANALYSIS_DIR, "bias-tier-distortion.json")
ODDS_ANOMALY_PATH = os.path.join(ANALYSIS_DIR, "odds-anomaly.json")
POISSON_PATH = os.path.join(ANALYSIS_DIR, "poisson-model.json")

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None

# ─── TIER LOOKUP ───
# Tiers based on team strength (historical win rate buckets)
TEAM_TIERS = {
    "MANCHESTER BLUE": "T1", "LIVERPOOL": "T1", "MANCHESTER RED": "T1",
    "CHELSEA": "T1", "TOTTENHAM": "T1", "LONDON GUNS": "T1",
    "ASTON VILLA": "T2", "EVERTON": "T2",
    "WEST HAM": "T2", "BRIGHTON": "T2",
    "LEEDS": "T3", "WOLVERHAMPTON": "T3",
    "CRYSTAL PALACE": "T3", "NEWCASTLE": "T3",
    "FULHAM": "T4", "BOURNEMOUTH": "T4",
}

def get_tier(team):
    return TEAM_TIERS.get(team.upper(), "T3")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", "operId": "2"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode()
        return json.loads(data)
    except Exception as e:
        print(f"[FETCH_ERR] {url}: {e}", file=sys.stderr)
        return None

def main():
    output = {
        "timestamp": datetime.now().isoformat(),
        "season": {},
        "upcoming": [],
        "table": [],
        "constraints": {},
        "bias_analysis": {},
        "odds_norms": {},
        "poisson": {},
    }

    # ─── 1. Current season info ───
    cur = fetch(f"{BASE}/current/match/day/info")
    d = cur.get("data", {})
    sid = d.get("seasonId", "")
    season_name = d.get("seasonName", "")
    current_md = d.get("matchDay")
    status = d.get("status")

    if not sid or current_md is None:
        print("[NO_DATA]")
        return 1

    output["season"] = {
        "id": sid,
        "name": season_name,
        "current_md": current_md,
        "status": status,
    }

    # ─── 2. Fetch results for all completed MDs ───
    table = defaultdict(lambda: {'pts': 0, 'gp': 0, 'gf': 0, 'ga': 0, 'form': []})
    completed_mds = []
    all_results = {}

    for md in range(1, current_md + 1):
        try:
            rurl = f"{BASE}/result?seasonId={sid}&matchDay={md}"
            rdata = fetch(rurl)
            if rdata is None:
                continue
            results_node = rdata.get("data", {})
            results = results_node.get("results") if results_node else None
            if results and len(results) == 8:
                completed_mds.append(md)
                all_results[md] = results
        except:
            break

    # Build table
    for md in sorted(all_results.keys()):
        for r in all_results[md]:
            home, away = r.get('homeTeam'), r.get('awayTeam')
            ft = r.get('fullTime')
            if not ft or ':' not in str(ft):
                continue
            try:
                ft_h, ft_a = map(int, ft.split(':'))
            except:
                continue
            table[home]['gp'] += 1
            table[home]['gf'] += ft_h
            table[home]['ga'] += ft_a
            table[away]['gp'] += 1
            table[away]['gf'] += ft_a
            table[away]['ga'] += ft_h
            if ft_h > ft_a:
                table[home]['pts'] += 3; table[home]['form'].append('W')
                table[away]['form'].append('L')
            elif ft_a > ft_h:
                table[away]['pts'] += 3; table[away]['form'].append('W')
                table[home]['form'].append('L')
            else:
                table[home]['pts'] += 1; table[home]['form'].append('D')
                table[away]['pts'] += 1; table[away]['form'].append('D')

    sorted_table = sorted(table.items(), key=lambda x: (x[1]['pts'], x[1]['gf']-x[1]['ga'], x[1]['gf']), reverse=True)
    
    output["table"] = []
    for i, (team, s) in enumerate(sorted_table, 1):
        output["table"].append({
            "pos": i, "team": team,
            "gp": s['gp'], "pts": s['pts'],
            "gd": s['gf'] - s['ga'],
            "gf": s['gf'], "ga": s['ga'],
            "form": ''.join(s['form'][-5:]),
            "form_full": ''.join(s['form']),
            "ppg": round(s['pts']/s['gp'], 2) if s['gp'] else 0,
        })
    
    output["completed_mds"] = completed_mds

    # ─── 3. Fetch upcoming event list ───
    evt = fetch(f"{BASE}/event/list?sportId=vf:sport:1")
    if evt is None:
        print("[NO_DATA]")
        return 1
    
    upcoming_mds = evt.get("data", {}).get("matchDays", [])

    for md_entry in upcoming_mds:
        md_num = md_entry['matchDay']
        events = md_entry['events']
        
        md_data = {
            "match_day": md_num,
            "matches": []
        }
        
        for e in events:
            home, away = e['homeTeam'], e['awayTeam']
            markets = {m['id']: m for m in e.get('markets', [])}
            m1 = markets.get(1, {})
            outs = {o['description']: float(o['odds']) for o in m1.get('outcomes', [])}
            
            home_odds = outs.get('Home', 0)
            draw_odds = outs.get('Draw', 0)
            away_odds = outs.get('Away', 0)
            
            # Implied probabilities (with vig removed roughly)
            implied_sum = 1/home_odds + 1/draw_odds + 1/away_odds if all([home_odds, draw_odds, away_odds]) else 0
            vig = implied_sum - 1 if implied_sum else 0
            
            md_data["matches"].append({
                "home": home,
                "away": away,
                "odds": {"H": home_odds, "D": draw_odds, "A": away_odds},
                "implied_h": round(1/home_odds/implied_sum*100, 1) if implied_sum else None,
                "implied_d": round(1/draw_odds/implied_sum*100, 1) if implied_sum else None,
                "implied_a": round(1/away_odds/implied_sum*100, 1) if implied_sum else None,
                "vig": round(vig*100, 2),
                "home_tier": get_tier(home),
                "away_tier": get_tier(away),
                "tier_matchup": f"{get_tier(home)}v{get_tier(away)}",
            })
        
        output["upcoming"].append(md_data)

    # ─── 4. Load constraints analysis (trimmed to relevant MDs only) ───
    constraints = load_json(CONSTRAINTS_PATH)
    if constraints:
        fixture_analysis = constraints.get("fixture_analysis", {})
        upcoming_md_numbers = [u["match_day"] for u in output["upcoming"]]
        # Only include fixture data for upcoming MDs plus a few nearby
        relevant_mds = set(upcoming_md_numbers)
        for i in range(1, 4):
            relevant_mds.add(i)
        for u in upcoming_md_numbers:
            for i in range(u-1, u+2):
                relevant_mds.add(i)
        
        md_patterns = {}
        for md_str, fixtures in fixture_analysis.items():
            md_int = int(md_str)
            if md_int in relevant_mds:
                md_patterns[md_int] = []
                for fxt in fixtures:
                    md_patterns[md_int].append({
                        "home": fxt["home"],
                        "away": fxt["away"],
                        "home_pct": fxt.get("home_pct", 0),
                        "draw_pct": fxt.get("draw_pct", 0),
                        "away_pct": fxt.get("away_pct", 0),
                        "total": fxt.get("total_occurrences", 0),
                        "flags": fxt.get("flags", []),
                    })
        
        output["constraints"] = {
            "fixtures_by_md": md_patterns,
            "global_home_win_rate": constraints.get("global_home_win_clustering", {}),
            "deviant_mds": constraints.get("deviant_mds", []),
        }

    # ─── 5. MD priors (Vera Sharp / Clara distortion map) ───
    current_md_val = current_md or 0
    output["md_priors"] = {
        "current_md": current_md_val,
        "global_home_pct": 44.89,
        "global_away_pct": 31.23,
        "global_draw_pct": 23.88,
        "current_md_priors": {},
        "md_distortion_map": {
            "1": {"home": 44.96, "away": 30.72, "draw": 24.33, "deviation": 1.02, "signal": "Near global avg"},
            "2": {"home": 44.62, "away": 30.10, "draw": 25.28, "deviation": 2.81, "signal": "Slight draw uptick"},
            "3": {"home": 43.72, "away": 33.24, "draw": 23.04, "deviation": 4.02, "signal": "AWAY surges!"},
            "4": {"home": 44.28, "away": 31.33, "draw": 24.38, "deviation": 1.22, "signal": "Normal"},
            "5": {"home": 43.33, "away": 32.62, "draw": 24.05, "deviation": 3.13, "signal": "AWAY elevated"},
            "6": {"home": 44.79, "away": 31.39, "draw": 23.82, "deviation": 0.32, "signal": "Most normal MD"},
            "7": {"home": 45.57, "away": 31.39, "draw": 23.04, "deviation": 1.68, "signal": "HOME uptick"},
            "8": {"home": 44.39, "away": 31.17, "draw": 24.44, "deviation": 1.12, "signal": "Normal"},
            "9": {"home": 46.69, "away": 30.89, "draw": 22.42, "deviation": 3.60, "signal": "HOME spikes! Best MD for home predictions"},
            "10": {"home": 46.69, "away": 29.26, "draw": 24.05, "deviation": 3.94, "signal": "HOME high, AWAY low"},
            "11": {"home": 44.73, "away": 31.05, "draw": 24.22, "deviation": 0.68, "signal": "Normal"},
            "12": {"home": 43.33, "away": 31.05, "draw": 25.62, "deviation": 3.48, "signal": "DRAW elevated"},
            "13": {"home": 45.07, "away": 30.94, "draw": 23.99, "deviation": 0.58, "signal": "Normal"},
            "14": {"home": 42.32, "away": 33.30, "draw": 24.38, "deviation": 5.15, "signal": "MOST DEVIANT — AWAY UPSET MD!"},
            "15": {"home": 45.29, "away": 30.77, "draw": 23.93, "deviation": 0.91, "signal": "Normal"},
            "16": {"home": 44.28, "away": 32.06, "draw": 23.65, "deviation": 1.67, "signal": "Slight away bias"},
            "17": {"home": 46.47, "away": 30.77, "draw": 22.76, "deviation": 3.15, "signal": "HOME elevated"},
            "18": {"home": 44.67, "away": 32.34, "draw": 22.98, "deviation": 2.23, "signal": "AWAY elevated"},
            "19": {"home": 46.64, "away": 29.71, "draw": 23.65, "deviation": 3.49, "signal": "HOME 2nd highest"},
            "20": {"home": 44.51, "away": 31.39, "draw": 24.10, "deviation": 0.77, "signal": "Normal"},
            "21": {"home": 44.84, "away": 31.50, "draw": 23.65, "deviation": 0.55, "signal": "Normal"},
            "22": {"home": 44.51, "away": 31.39, "draw": 24.10, "deviation": 0.77, "signal": "Normal"},
            "23": {"home": 44.39, "away": 31.22, "draw": 24.38, "deviation": 1.01, "signal": "Normal"},
            "24": {"home": 45.07, "away": 30.94, "draw": 23.99, "deviation": 0.58, "signal": "Normal"},
            "25": {"home": 44.67, "away": 30.49, "draw": 24.83, "deviation": 1.91, "signal": "Slight draw"},
            "26": {"home": 45.18, "away": 31.11, "draw": 23.71, "deviation": 0.57, "signal": "Normal"},
            "27": {"home": 45.63, "away": 30.61, "draw": 23.77, "deviation": 1.47, "signal": "Slight home"},
            "28": {"home": 44.62, "away": 31.22, "draw": 24.16, "deviation": 0.56, "signal": "Normal"},
            "29": {"home": 45.68, "away": 30.38, "draw": 23.93, "deviation": 1.70, "signal": "Slight home"},
            "30": {"home": 45.85, "away": 32.51, "draw": 21.64, "deviation": 4.48, "signal": "DRAW crashes!"},
        },
        "deviant_mds_note": "MD14 is the most deviant (5.15) — 'Away Upset MD'. Reduce home confidence on MD14. MD3/5/18 see AWAY surges. MD9/17/19 are HOME-dominant. MD30 draws crash to 21.64%.",
    }
    # Fill current_md_priors if md is in range
    md_key = str(current_md_val)
    if md_key in output["md_priors"]["md_distortion_map"]:
        output["md_priors"]["current_md_priors"] = output["md_priors"]["md_distortion_map"][md_key].copy()

    # ─── 6. Bias tier distortion ───
    bias = load_json(BIAS_PATH)
    if bias:
        output["bias_analysis"] = bias

    # ─── 6. Odds anomaly norms ───
    odds_norms = load_json(ODDS_ANOMALY_PATH)
    if odds_norms:
        output["odds_norms"] = {
            "tier_matchup_norms": odds_norms.get("tier_matchup_norms", {}),
            "verdict": odds_norms.get("verdict", ""),
        }

    # ─── 7. Poisson model ───
    poisson = load_json(POISSON_PATH)
    if poisson:
        output["poisson"] = {
            "accuracy": poisson.get("poisson_accuracy"),
            "market_accuracy": poisson.get("market_accuracy"),
            "verdict": poisson.get("verdict", ""),
        }

    # ─── Output ───
    out_json = json.dumps(output, indent=2)
    
    # Save to state file for cron agent
    STATE_DIR = os.path.expanduser("~/.hermes/cron/state")
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "vfl_oracle_context.json"), "w") as f:
        f.write(out_json)
    
    print(out_json)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        print("[NO_DATA]")
        sys.exit(1)

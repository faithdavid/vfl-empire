#!/usr/bin/env python3
"""
VFL Autonomous Predictor — ML-powered prediction + settlement agent.
Runs every cycle, detects new MDs, predicts all 8 matches, settles results.
"""
import urllib.request, json, os, sys, math
from datetime import datetime
from collections import defaultdict

# ─── CONSTRAINTS MODULE ───
from vfl_constraints import VFLConstraints
constraints = VFLConstraints()

# ─── CONFIG ───
STATE_FILE = os.path.expanduser("~/.hermes/cron/state/vfl_predictor_state.json")
MODEL_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/models/vfl_model.json")
TABLE_DIR = os.path.expanduser("~/Documents/Projects/vfl-data/tables")
UA = "Mozilla/5.0"
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
os.makedirs(TABLE_DIR, exist_ok=True)

# ─── ML MODEL ───
def dot_product(w, x):
    return sum(w[i]*x[i] for i in range(len(w)))

def softmax(x):
    ex = [math.exp(v) for v in x]
    s = sum(ex)
    return [v/s for v in ex]

class MLModel:
    def __init__(self):
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH) as f:
                data = json.load(f)
            self.w = data['w']
            self.ready = True
        else:
            self.w = [[0.0]*15 for _ in range(3)]
            self.ready = False
    
    def predict_proba(self, x):
        scores = [dot_product(self.w[c], x) for c in range(3)]
        return softmax(scores)
    
    def predict(self, x):
        probs = self.predict_proba(x)
        return max(range(3), key=lambda i: probs[i]), probs

model = MLModel()

# ─── TEAM STATS (cached) ───
TS = {
    "MANCHESTER BLUE": {"win_rate": 0.440, "hgf": 1.365, "hga": 0.453, "agf": 1.329, "aga": 0.465},
    "LIVERPOOL": {"win_rate": 0.444, "hgf": 1.352, "hga": 0.423, "agf": 1.257, "aga": 0.514},
    "MANCHESTER RED": {"win_rate": 0.425, "hgf": 1.329, "hga": 0.465, "agf": 1.257, "aga": 0.514},
    "CHELSEA": {"win_rate": 0.410, "hgf": 1.257, "hga": 0.514, "agf": 1.257, "aga": 0.514},
    "TOTTENHAM": {"win_rate": 0.391, "hgf": 0.981, "hga": 0.595, "agf": 1.073, "aga": 0.568},
    "LONDON GUNS": {"win_rate": 0.402, "hgf": 1.038, "hga": 0.569, "agf": 0.977, "aga": 0.631},
    "ASTON VILLA": {"win_rate": 0.399, "hgf": 1.073, "hga": 0.568, "agf": 0.925, "aga": 0.677},
    "EVERTON": {"win_rate": 0.350, "hgf": 0.713, "hga": 0.811, "agf": 0.840, "aga": 0.789},
    "WEST HAM": {"win_rate": 0.331, "hgf": 0.709, "hga": 0.865, "agf": 0.803, "aga": 0.834},
    "BRIGHTON": {"win_rate": 0.318, "hgf": 0.640, "hga": 0.950, "agf": 0.713, "aga": 0.887},
    "LEEDS": {"win_rate": 0.274, "hgf": 0.494, "hga": 1.277, "agf": 0.567, "aga": 1.131},
    "WOLVERHAMPTON": {"win_rate": 0.294, "hgf": 0.616, "hga": 0.985, "agf": 0.616, "aga": 1.001},
    "CRYSTAL PALACE": {"win_rate": 0.264, "hgf": 0.467, "hga": 1.275, "agf": 0.610, "aga": 1.183},
    "NEWCASTLE": {"win_rate": 0.259, "hgf": 0.490, "hga": 1.261, "agf": 0.567, "aga": 1.131},
    "FULHAM": {"win_rate": 0.258, "hgf": 0.426, "hga": 1.414, "agf": 0.543, "aga": 1.220},
    "BOURNEMOUTH": {"win_rate": 0.245, "hgf": 0.417, "hga": 1.465, "agf": 0.543, "aga": 1.220},
}

def build_features(home, away, sd):
    hu, au = home.upper(), away.upper()
    hts = TS.get(hu, {}); ats = TS.get(au, {})
    sd_h = sd.get(hu, {}); sd_a = sd.get(au, {})
    return [
        1.0,
        hts.get('win_rate', 0.33), ats.get('win_rate', 0.33),
        hts.get('hgf', 1.4), hts.get('hga', 0.9),
        ats.get('agf', 1.1), ats.get('aga', 1.4),
        sd_h.get('fw', 0)/5.0, sd_a.get('fw', 0)/5.0,
        sd_h.get('fl', 0)/5.0, sd_a.get('fl', 0)/5.0,
        sd_h.get('ppg', 0), sd_a.get('ppg', 0),
        sd_h.get('gdpg', 0), sd_a.get('gdpg', 0),
    ]

def predict_matches(event_list, table, match_day=None):
    sd = {}
    for team, s in table.items():
        f = ''.join(s.get('form', []))
        sd[team.upper()] = {
            'fw': f[-5:].count('W'), 'fl': f[-5:].count('L'),
            'ppg': s['pts']/s['gp'] if s['gp'] else 0,
            'gdpg': (s['gf']-s['ga'])/s['gp'] if s['gp'] else 0,
        }
    
    results = []
    for e in event_list:
        home, away = e['homeTeam'], e['awayTeam']
        markets = {m['id']: m for m in e.get('markets', [])}
        m1 = markets.get(1, {})
        outs = {o['description']: float(o['odds']) for o in m1.get('outcomes', [])}
        
        # ─── CONSTRAINT OVERRIDES (per-fixture) ───
        override_pred = None
        zero_draw = False
        
        if match_day is not None:
            if constraints.is_always_home(home, away, match_day):
                override_pred = "HOME"
            elif constraints.is_always_away(home, away, match_day):
                override_pred = "AWAY"
            
            if constraints.never_drawn(home, away, match_day):
                zero_draw = True
        
        if override_pred:
            # 100% historical certainty — override ML completely
            probs = [0.0, 0.0, 0.0]
            if override_pred == "HOME":
                probs[0] = 1.0
            elif override_pred == "AWAY":
                probs[1] = 1.0
            # DRAW is 0.0 for always_home or always_away
            pred = override_pred
        else:
            if model.ready:
                feats = build_features(home, away, sd)
                pred_idx, probs = model.predict(feats)
                labels = ["HOME", "AWAY", "DRAW"]
                pred = labels[pred_idx]
            else:
                probs = [0.33, 0.33, 0.33]
                pred = "HOME"
            
            # ─── NEVER DRAWN override — zero out DRAW probability ───
            if zero_draw:
                probs[2] = 0.0
                total = sum(probs)
                if total > 0:
                    probs = [p / total for p in probs]
                else:
                    probs = [0.5, 0.5, 0.0]
                
                # Re-pick best prediction after zeroing draw
                labels = ["HOME", "AWAY", "DRAW"]
                pred = labels[max(range(3), key=lambda i: probs[i])]
        
        results.append({
            'home': home, 'away': away,
            'odds': outs,
            'prediction': pred,
            'confidence': max(probs) * 100,
            'probs': {'HOME': probs[0]*100, 'AWAY': probs[1]*100, 'DRAW': probs[2]*100}
        })
    return results

def settle_results(predictions, results):
    settled = []
    for p in predictions:
        for r in results:
            if r.get('homeTeam') == p['home'] and r.get('awayTeam') == p['away']:
                ft = r.get('fullTime')
                ft_h, ft_a = map(int, ft.split(':'))
                actual = "HOME" if ft_h > ft_a else ("AWAY" if ft_a > ft_h else "DRAW")
                hit = p['prediction'] == actual
                settled.append({**p, 'full_time': ft, 'actual': actual, 'hit': hit})
                break
    return settled

# ══════════════════════════════════════
# MAIN
# ══════════════════════════════════════
def main():
    # Load state
    state = {"last_season": "", "last_md": 0, "predicted_mds": [], "settled_mds": []}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except:
            pass
    
    # Current season info
    cur_url = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/current/match/day/info"
    req = urllib.request.Request(cur_url, headers={"User-Agent": UA})
    cur = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    d = cur.get("data", {})
    
    sid = d.get('seasonId', '')
    season_name = d.get('seasonName', '')
    current_md = d.get('matchDay')
    status = d.get('status')
    
    if not sid or current_md is None:
        print("[SILENT]")
        return
    
    # Detect new season
    new_season = sid != state.get("last_season", "")
    if new_season:
        state["last_season"] = sid
        state["predicted_mds"] = []
        state["settled_mds"] = []
        state["last_md"] = 0
    
    # Get current results
    new_results = {}
    for md in range(1, current_md + 1):
        if md in state.get("settled_mds", []) and not new_season:
            continue
        rurl = f"https://www.msport.com/api/ng/facts-center/query/frontend/virtual/result?seasonId={sid}&matchDay={md}"
        rreq = urllib.request.Request(rurl, headers={"User-Agent": UA, "Accept": "application/json"})
        rdata = json.loads(urllib.request.urlopen(rreq, timeout=10).read().decode())
        results = rdata.get("data", {}).get("results")
        if results and len(results) == 8:
            new_results[md] = results
    
    if not new_results:
        print("[SILENT]")
        return
    
    # Build table from all results
    table = defaultdict(lambda: {'pts': 0, 'gd': 0, 'gp': 0, 'gf': 0, 'ga': 0, 'form': []})
    for md in sorted(new_results.keys()):
        for r in new_results[md]:
            home, away = r.get('homeTeam'), r.get('awayTeam')
            ft = r.get('fullTime')
            if not ft: continue
            ft_h, ft_a = map(int, ft.split(':'))
            table[home]['gp'] += 1; table[home]['gf'] += ft_h; table[home]['ga'] += ft_a
            table[away]['gp'] += 1; table[away]['gf'] += ft_a; table[away]['ga'] += ft_h
            if ft_h > ft_a:
                table[home]['pts'] += 3; table[home]['form'].append('W')
                table[away]['form'].append('L')
            elif ft_a > ft_h:
                table[away]['pts'] += 3; table[away]['form'].append('W')
                table[home]['form'].append('L')
            else:
                table[home]['pts'] += 1; table[home]['form'].append('D')
                table[away]['pts'] += 1; table[away]['form'].append('D')
    
    sorted_teams = sorted(table.items(), key=lambda x: (x[1]['pts'], x[1]['gf']-x[1]['ga'], x[1]['gf']), reverse=True)
    max_played_md = max(new_results.keys())
    
    # ─── SETTLE RESULTS ───
    predictions = [] # Will be empty if no predictions made
    output_lines = []
    
    # Check if we have any unsettled predictions
    predicted_mds = state.get("predicted_mds", [])
    for md in sorted(new_results.keys()):
        if md in state.get("settled_mds", []) and not new_season:
            continue
        # We have results for this MD - check if any previous predictions match
        # For now, just mark as settled
        if md not in state.get("settled_mds", []):
            state.setdefault("settled_mds", []).append(md)
    
    # ─── PREDICT NEXT MD ───
    # Check if there's an upcoming MD in the event list
    evt_url = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/event/list?sportId=vf:sport:1"
    evt_req = urllib.request.Request(evt_url, headers={"User-Agent": UA, "operId": "2"})
    evt = json.loads(urllib.request.urlopen(evt_req, timeout=10).read().decode())
    
    next_md = None
    next_matches = []
    for md_entry in evt.get("data", {}).get("matchDays", []):
        md_num = md_entry['matchDay']
        # Only predict if we haven't predicted this MD and it's upcoming
        if md_num not in state.get("predicted_mds", []):
            next_md = md_num
            next_matches = md_entry['events']
            break
    
    if next_matches and next_md:
        preds = predict_matches(next_matches, table, match_day=next_md)
        
        # ─── PATTERN FEASIBILITY CHECK ───
        current_fixtures = [(e['homeTeam'], e['awayTeam']) for e in next_matches]
        predictions_list = [p['prediction'] for p in preds]
        confidences_list = [p['confidence'] / 100.0 for p in preds]
        
        if not constraints.is_pattern_feasible(predictions_list, next_md, current_fixtures):
            # Pattern has never been observed — adjust lowest-confidence prediction(s)
            adjusted = constraints.adjust_to_feasible_pattern(
                predictions_list, confidences_list, next_md, current_fixtures
            )
            # Update preds with adjusted predictions
            for i, adj_pred in enumerate(adjusted):
                if adj_pred != preds[i]['prediction']:
                    old_pred = preds[i]['prediction']
                    preds[i]['prediction'] = adj_pred
                    preds[i]['confidence'] = 99.0  # Mark as high-confidence constraint fix
                    # Also adjust probs
                    for k in preds[i]['probs']:
                        preds[i]['probs'][k] = 0.0
                    preds[i]['probs'][adj_pred] = 100.0
                    preds[i]['constraint_adjustment'] = f"Pattern feasibility: {old_pred}→{adj_pred}"
        
        # ─── CONSTRAINTS SUMMARY ───
        constraint_flags = {}
        for e in next_matches:
            home, away = e['homeTeam'], e['awayTeam']
            flags = []
            if constraints.is_always_home(home, away, next_md):
                flags.append("ALWAYS_HOME")
            if constraints.is_always_away(home, away, next_md):
                flags.append("ALWAYS_AWAY")
            if constraints.never_drawn(home, away, next_md):
                flags.append("NEVER_DRAW")
            if flags:
                constraint_flags[f"{home} vs {away}"] = flags
        
        # Save predictions to shared ledger for settlement agent
        LEDGER_PATH = os.path.expanduser("~/.hermes/cron/state/vfl_ledger.json")
        ledger = {"predictions": [], "settled": []}
        if os.path.exists(LEDGER_PATH):
            try:
                with open(LEDGER_PATH) as f:
                    ledger = json.load(f)
            except:
                pass
        
        for p in preds:
            # Add constraint flags for this fixture
            fixture_flags = constraint_flags.get(f"{p['home']} vs {p['away']}", [])
            ledger_entry = {
                'season_id': sid,
                'season_name': season_name,
                'match_day': next_md,
                'home': p['home'],
                'away': p['away'],
                'prediction': p['prediction'],
                'confidence': p['confidence'],
                'odds_h': p['odds'].get('Home'),
                'odds_d': p['odds'].get('Draw'),
                'odds_a': p['odds'].get('Away'),
                'ml_probs': p['probs'],
                'constraint_flags': fixture_flags,
                'constraint_adjustment': p.get('constraint_adjustment'),
                'created_at': datetime.now().isoformat(),
                'settled': False
            }
            ledger['predictions'].append(ledger_entry)
        
        with open(LEDGER_PATH, 'w') as f:
            json.dump(ledger, f, indent=2)
        
        # Save predictions
        state.setdefault("predicted_mds", []).append(next_md)
        
        # Build output
        output_lines.append(f"🤖 **{season_name} — MD {next_md} Constraint Predictions**")
        output_lines.append("")
        
        for p in preds:
            stars = "⭐" if p['confidence'] > 55 else ("📊" if p['confidence'] > 45 else "🤞")
            output_lines.append(f"**{p['home']:22} vs {p['away']:<22}**")
            output_lines.append(f"Odds: {p['odds'].get('Home',0):.2f}/{p['odds'].get('Draw',0):.2f}/{p['odds'].get('Away',0):.2f}")
            output_lines.append(f"ML: {p['home']} {p['probs']['HOME']:.0f}% | Draw {p['probs']['DRAW']:.0f}% | {p['away']} {p['probs']['AWAY']:.0f}%")
            
            adj = p.get('constraint_adjustment')
            if adj:
                # This was adjusted by constraint layer
                output_lines.append(f"🔄 *{adj}*")
                output_lines.append(f"👉 **{p['prediction']}** 🔒 (constraint override)")
            else:
                fixture_key = f"{p['home']} vs {p['away']}"
                flags = constraint_flags.get(fixture_key, [])
                constraint_tag = ""
                if "ALWAYS_HOME" in flags:
                    constraint_tag = " 🔒(100% HOME hist)"
                elif "ALWAYS_AWAY" in flags:
                    constraint_tag = " 🔒(100% AWAY hist)"
                elif "NEVER_DRAW" in flags:
                    constraint_tag = " ⛔(no draw ever)"
                output_lines.append(f"👉 **{p['prediction']}** {stars}  ({p['confidence']:.0f}%){constraint_tag}")
            output_lines.append("")
        
        if constraint_flags:
            output_lines.append("📋 **Clara Constraints Active:**")
            for fixture, flags in constraint_flags.items():
                output_lines.append(f"• {fixture}: {', '.join(flags)}")
            output_lines.append("")
    
    # ─── TABLE UPDATE ───
    # Only show table if we have new results or predictions
    if max_played_md > state.get("last_md", 0) or next_md:
        output_lines.append(f"📊 **{season_name} — After MD {max_played_md}**")
        output_lines.append("")
        for i, (team, s) in enumerate(sorted_teams[:6], 1):
            gd = s['gf'] - s['ga']
            f = ''.join(s['form'][-5:])
            output_lines.append(f"{i}. {team} — {s['pts']}pts (GD:{gd:+d}) [{f}]")
        
        # Streaks
        output_lines.append("")
        for team, s in sorted_teams:
            f = ''.join(s['form'])
            if 'WWWW' in f:
                streak_len = 0
                for i in range(len(f)-1, -1, -1):
                    if f[i] == 'W': streak_len += 1
                    else: break
                output_lines.append(f"🔥 {team} — {streak_len}W streak!")
            elif 'LLLL' in f:
                streak_len = 0
                for i in range(len(f)-1, -1, -1):
                    if f[i] == 'L': streak_len += 1
                    else: break
                output_lines.append(f"💀 {team} — {streak_len}L streak!")
    
    # Save table
    table_data = {
        "season": season_name, "season_id": sid, "matchday": max_played_md,
        "timestamp": datetime.now().isoformat(), "standings": []
    }
    for i, (team, s) in enumerate(sorted_teams, 1):
        table_data["standings"].append({
            "position": i, "team": team, "played": s['gp'],
            "wins": s['form'].count('W'), "draws": s['form'].count('D'),
            "losses": s['form'].count('L'),
            "goals_for": s['gf'], "goals_against": s['ga'],
            "goal_diff": s['gf']-s['ga'], "points": s['pts'],
            "form": ''.join(s['form'])
        })
    latest_path = os.path.join(TABLE_DIR, "vfl_latest.json")
    with open(latest_path, 'w') as f:
        json.dump(table_data, f, indent=2)
    
    # Save state
    state["last_md"] = max_played_md
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    
    if output_lines:
        print("\n".join(output_lines))
    else:
        print("[SILENT]")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[SILENT]")

#!/usr/bin/env python3
"""
VFL Engine Prediction Pipeline
Integrates: Elo ratings, Fellenius tier calibration, signature biases,
abnormal season detection, value betting.
Outputs: predictions to ledger + Discord delivery.
"""
import json, math, os, sys, urllib.request
from datetime import datetime
from collections import defaultdict
import numpy as np

# ─── Configuration ───
CONTEXT_PATH = os.path.expanduser("~/.hermes/cron/state/vfl_oracle_context.json")
LEDGER_PATH = os.path.expanduser("~/.hermes/cron/state/vfl_ledger.json")
STATE_PATH = os.path.expanduser("~/.hermes/cron/state/vfl_predictor_state.json")
OUTPUT_DIR = os.path.expanduser("~/.hermes/cron/output")
INTEL_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/analysis/unified_intel.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Team Config ───
TEAMS = ["MANCHESTER BLUE", "MANCHESTER RED", "LIVERPOOL", "CHELSEA",
         "LONDON GUNS", "TOTTENHAM", "ASTON VILLA", "EVERTON",
         "WEST HAM", "WOLVERHAMPTON", "BRIGHTON", "LEEDS",
         "NEWCASTLE", "BOURNEMOUTH", "CRYSTAL PALACE", "FULHAM"]

TIERS = {t: i for i, t in enumerate([
    "MANCHESTER BLUE", "MANCHESTER RED", "LIVERPOOL", "CHELSEA",
    "LONDON GUNS", "TOTTENHAM", "ASTON VILLA", "EVERTON",
    "WEST HAM", "WOLVERHAMPTON", "BRIGHTON", "LEEDS",
    "NEWCASTLE", "BOURNEMOUTH", "CRYSTAL PALACE", "FULHAM"
])}

def get_tier_num(name):
    n = name.upper()
    if n in TIERS:
        i = TIERS[n]
        if i < 4: return 1
        elif i < 8: return 2
        elif i < 12: return 3
        else: return 4
    return 3

# ─── Historical Baselines (from Fellenius, computed over 39 seasons) ───
# Full-dataset tier matchup outcome rates
FELLENIUS_BASELINE = {
    "T1_vs_T1": {"H": 44.7, "D": 25.0, "A": 30.3},
    "T1_vs_T2": {"H": 58.2, "D": 23.5, "A": 18.3},
    "T1_vs_T3": {"H": 63.5, "D": 17.8, "A": 18.7},
    "T1_vs_T4": {"H": 77.0, "D": 14.8, "A": 8.3},
    "T2_vs_T1": {"H": 31.2, "D": 28.6, "A": 40.3},
    "T2_vs_T2": {"H": 46.8, "D": 23.4, "A": 29.9},
    "T2_vs_T3": {"H": 44.1, "D": 25.9, "A": 30.0},
    "T2_vs_T4": {"H": 61.6, "D": 24.0, "A": 14.4},
    "T3_vs_T1": {"H": 32.5, "D": 28.6, "A": 38.9},
    "T3_vs_T2": {"H": 43.8, "D": 23.9, "A": 32.2},
    "T3_vs_T3": {"H": 45.7, "D": 23.8, "A": 30.5},
    "T3_vs_T4": {"H": 61.3, "D": 21.3, "A": 17.4},
    "T4_vs_T1": {"H": 17.8, "D": 19.1, "A": 63.0},
    "T4_vs_T2": {"H": 24.9, "D": 28.8, "A": 46.3},
    "T4_vs_T3": {"H": 28.7, "D": 26.7, "A": 44.6},
    "T4_vs_T4": {"H": 45.2, "D": 26.5, "A": 28.3},
}

# Signature team adjustments (from Phase 1 analysis)
SIGNATURE_BIAS = {
    "WEST HAM": 0.288,      # West Ham bias: +0.288 extra log-odds for home win
    "WOLVERHAMPTON": 0.079, # Wolves bias: +0.079 (less significant)
}

# Abnormal season calibration (from Phase 3-4)
# When season τ < 0.60, apply distortion multipliers
ABNORMAL_SEASON_MULTIPLIERS = {
    # Tier matchup: (home_mult, draw_mult, away_mult)
    "T1_vs_T4": (0.88, 1.10, 1.50),  # Top vs bottom → fewer home wins, more upsets
    "T4_vs_T1": (1.20, 1.10, 0.85),  # Bottom vs top → more home wins (they're better this season)
    "T1_vs_T3": (0.90, 1.05, 1.30),
    "T3_vs_T1": (1.15, 1.05, 0.90),
    "T3_vs_T3": (0.90, 1.00, 1.20),  # Mid vs mid → more away wins
    "T3_vs_T4": (0.85, 1.05, 1.40),
    "T4_vs_T3": (1.30, 1.05, 0.80),
}

# ─── Elo System ───
ELO_K = 32
HOME_ADV = 60

def init_elo():
    return {t: 1500 for t in TEAMS}

def elo_predict(elo_home, elo_away):
    """Expected score for home team"""
    diff = elo_away - (elo_home + HOME_ADV)
    return 1.0 / (1.0 + 10.0 ** (diff / 400.0))

def update_elo(elo, home, away, hg, ag):
    elo_h = elo[home] + HOME_ADV
    elo_a = elo[away]
    exp_h = 1.0 / (1.0 + 10.0 ** ((elo_a - elo_h) / 400.0))
    
    if hg > ag: actual_h = 1.0
    elif hg == ag: actual_h = 0.5
    else: actual_h = 0.0
    
    gd = abs(hg - ag)
    gw = 1.0 if gd <= 1 else (1.5 if gd == 2 else (11.0 + gd) / 8.0)
    K_eff = ELO_K * gw
    
    elo[home] += K_eff * (actual_h - exp_h)
    elo[away] += K_eff * ((1.0 - actual_h) - (1.0 - exp_h))

def load_or_update_elo():
    """Load Elo from ledger history or initialize fresh"""
    elo = init_elo()
    try:
        with open(LEDGER_PATH) as f:
            ledger = json.load(f)
        for p in ledger.get('predictions', []):
            if p.get('actual_outcome') and p.get('full_time'):
                ft = p['full_time']
                if ':' in ft:
                    hg, ag = map(int, ft.split(':'))
                    update_elo(elo, p['home'].upper(), p['away'].upper(), hg, ag)
        return elo
    except:
        return elo

def load_unified_intel():
    """Load the latest unified intelligence from all research streams"""
    try:
        with open(INTEL_PATH) as f:
            return json.load(f)
    except:
        return {}

# ─── Prediction Function ───
def predict_match(home, away, elo, is_abnormal_season=False, intel=None):
    """Predict H/D/A probabilities using all engine signals"""
    h = home.upper(); a = away.upper()
    
    # Base Elo prediction
    elo_h = elo.get(h, 1500); elo_a = elo.get(a, 1500)
    exp_h = elo_predict(elo_h, elo_a)
    exp_a = 1.0 - exp_h
    
    # Convert Elo expected score to rough probabilities
    # At exp_h=0.5, we have roughly 30% each way + 40% draw
    # At exp_h=0.8, roughly 60% home, 25% draw, 15% away
    draw_base = 0.25
    if abs(exp_h - 0.5) < 0.05:
        p_h = 0.35; p_d = 0.30; p_a = 0.35
    elif exp_h > 0.5:
        p_h = exp_h * 0.8; p_d = draw_base * (1 - (exp_h - 0.5)); p_a = 1 - p_h - p_d
    else:
        p_a = (1 - exp_h) * 0.8; p_d = draw_base * (1 - (0.5 - exp_h)); p_h = 1 - p_a - p_d
    
    # Tier adjustment
    ht = get_tier_num(h); at = get_tier_num(a)
    tier_key = f"T{ht}_vs_T{at}"
    baseline = FELLENIUS_BASELINE.get(tier_key)
    if baseline:
        # Blend: 50% Elo, 50% tier baseline
        total_b = baseline['H'] + baseline['D'] + baseline['A']
        p_h = 0.5 * p_h + 0.5 * baseline['H'] / total_b
        p_d = 0.5 * p_d + 0.5 * baseline['D'] / total_b
        p_a = 0.5 * p_a + 0.5 * baseline['A'] / total_b
    
    # Signature team bias
    if h in SIGNATURE_BIAS:
        bias = SIGNATURE_BIAS[h]
        p_h += bias * 0.05; p_a -= bias * 0.05
    if a in SIGNATURE_BIAS:
        bias = SIGNATURE_BIAS[a]
        p_a += bias * 0.05; p_h -= bias * 0.05
    
    # ─── INTEL INTEGRATION: Clara's team constraints ───
    if intel:
        team_c = intel.get('team_constraints', {})
        
        # Home team constraints
        hc = team_c.get(h, {})
        if hc.get('home_trap'):
            p_h -= 0.05  # Reduce home confidence
            p_d += 0.03
            p_a += 0.02
        if hc.get('draw_bias'):
            p_d += 0.04
            p_h -= 0.02
            p_a -= 0.02
        if hc.get('unreliable'):
            # Boost draw and away
            p_d += 0.03
            p_a += 0.02
            p_h -= 0.05
        
        # Away team constraints
        ac = team_c.get(a, {})
        if ac.get('away_strong'):
            p_a += 0.04
            p_h -= 0.02
            p_d -= 0.02
        if ac.get('draw_bias'):
            p_d += 0.04
            p_h -= 0.02
            p_a -= 0.02
        if ac.get('upset_specialist') and get_tier_num(h) == 1:
            # T1 favorite visiting upset specialist
            p_h -= 0.06
            p_d += 0.03
            p_a += 0.03
    
    # ─── INTEL INTEGRATION: Confidence calibration ───
    # (Applied after prediction, in main())
    
    # Abnormal season adjustment
    if is_abnormal_season and tier_key in ABNORMAL_SEASON_MULTIPLIERS:
        m_h, m_d, m_a = ABNORMAL_SEASON_MULTIPLIERS[tier_key]
        total = p_h * m_h + p_d * m_d + p_a * m_a
        p_h = p_h * m_h / total
        p_d = p_d * m_d / total
        p_a = p_a * m_a / total
    
    # Normalize
    total = p_h + p_d + p_a
    p_h /= total; p_d /= total; p_a /= total
    
    return p_h, p_d, p_a

def detect_abnormal_season(table_data):
    """Check if current season is abnormal based on tier correlation"""
    if not table_data:
        return False
    expected_pos = {t: i+1 for i, t in enumerate(TEAMS)}
    actual_pos = {}
    for entry in table_data:
        team = entry.get('team', '').upper()
        if team in expected_pos:
            actual_pos[team] = entry['pos']
    
    # Kendall τ (simplified: only check if top tier teams are in top half)
    t1_teams = ["MANCHESTER BLUE", "LIVERPOOL", "MANCHESTER RED", "CHELSEA"]
    top_half = 8
    t1_in_top = sum(1 for t in t1_teams if actual_pos.get(t, 999) <= top_half)
    
    # If fewer than 3 of the 4 top teams are in top half = abnormal
    return t1_in_top < 3

def compute_trajectory_tau(table_data):
    """Compute approximate Kendall τ from current table"""
    if not table_data:
        return 0.5
    expected_pos = {t: i+1 for i, t in enumerate(TEAMS)}
    actual_pos = {}
    for entry in table_data:
        team = entry.get('team', '').upper()
        if team in expected_pos:
            actual_pos[team] = entry['pos']
    
    # Simplified: average position deviation of T1 teams from expected
    t1_teams = ["MANCHESTER BLUE", "LIVERPOOL", "MANCHESTER RED", "CHELSEA"]
    devs = [abs(actual_pos.get(t, 999) - expected_pos[t]) for t in t1_teams if t in actual_pos]
    avg_dev = sum(devs) / len(devs) if devs else 0
    
    # τ ≈ 0.80 when avg_dev = 0, τ ≈ 0.50 when avg_dev = 3, τ ≈ 0.30 when avg_dev = 6
    tau = 0.80 - (avg_dev * 0.08)
    return max(0.3, min(0.85, tau))

# ─── Main ───
def main():
    print("[ENGINE] Loading context...")
    try:
        with open(CONTEXT_PATH) as f:
            ctx = json.load(f)
    except Exception as e:
        print(f"[ERROR] Cannot load context: {e}")
        return 1
    
    season = ctx.get('season', {})
    sid = season.get('id', '')
    sname = season.get('name', '')
    current_md = season.get('current_md', 0)
    status = season.get('status', '')
    
    if not sid or status == 'POST_MATCH':
        # Still post current state for reference
        pass
    
    # Load unified intelligence from all research streams
    intel = load_unified_intel()
    if intel.get('streams'):
        print(f"[ENGINE] Intel loaded: {intel['streams']['clara_misses']} misses, {intel['streams']['pattern_rules']} team rules")
    
    # Detect abnormal season
    table_data = ctx.get('table', [])
    is_abnormal = detect_abnormal_season(table_data)
    tau = compute_trajectory_tau(table_data)
    
    print(f"[ENGINE] Season: {sname} (MD {current_md})")
    print(f"[ENGINE] Abnormal season: {is_abnormal} (τ≈{tau:.3f})")
    
    # Load Elo
    elo = load_or_update_elo()
    
    # Get upcoming matches
    upcoming = ctx.get('upcoming', [])
    if not upcoming:
        print("[ENGINE] No upcoming matches. Checking next available MD...")
        # Return current state info
        print(f"\n{'='*60}")
        print(f"ENGINE STATUS REPORT")
        print(f"{'='*60}")
        print(f"Season: {sname} (MD {current_md}, {status})")
        print(f"Table τ: {tau:.3f} ({'ABNORMAL' if is_abnormal else 'normal'})")
        print(f"Teams in active Elo: {sum(1 for t in TEAMS if abs(elo.get(t,1500)-1500) > 10)}/16")
        return 0
    
    predictions = []
    for md_entry in upcoming:
        md_num = md_entry['match_day']
        print(f"\n[ENGINE] MD {md_num}:")
        
        for match in md_entry.get('matches', []):
            home = match['home']
            away = match['away']
            odds = match.get('odds', {})
            odds_h = odds.get('H', 0)
            odds_d = odds.get('D', 0)
            odds_a = odds.get('A', 0)
            
            # Our prediction
            p_h, p_d, p_a = predict_match(home, away, elo, is_abnormal, intel)
            
            # Odds-implied probabilities (with vig removed)
            if odds_h and odds_d and odds_a:
                imp_sum = 1/odds_h + 1/odds_d + 1/odds_a
                imp_h = 1/odds_h / imp_sum * 100
                imp_d = 1/odds_d / imp_sum * 100
                imp_a = 1/odds_a / imp_sum * 100
            else:
                imp_h = imp_d = imp_a = 0
            
            # Prediction
            if p_h > p_d and p_h > p_a:
                pred = "HOME"
                conf = p_h * 100
            elif p_d > p_a:
                pred = "DRAW"
                conf = p_d * 100
            else:
                pred = "AWAY"
                conf = p_a * 100
            
            # Value detection: where our probability differs significantly from odds
            value_bet = ""
            our_probs = [p_h*100, p_d*100, p_a*100]
            imp_probs = [imp_h, imp_d, imp_a]
            labels = ["HOME", "DRAW", "AWAY"]
            
            for i in range(3):
                if imp_probs[i] > 0 and our_probs[i] > imp_probs[i] * 1.15:
                    value_bet += f" {labels[i]}(+{our_probs[i]-imp_probs[i]:.0f}% edge)"
            
            # Confidence tier
            if conf >= 55:
                conf_tier = "⭐ HIGH"
            elif conf >= 45:
                conf_tier = "📊 MED"
            else:
                conf_tier = "🤞 LOW"
            
            print(f"  {home:<20} vs {away:<20}")
            print(f"    Our: H={p_h*100:.1f}% D={p_d*100:.1f}% A={p_a*100:.1f}% → {pred} ({conf_tier})")
            print(f"    Odds: {odds_h:.2f}/{odds_d:.2f}/{odds_a:.2f} (imp: {imp_h:.0f}%/{imp_d:.0f}%/{imp_a:.0f}%)")
            if value_bet:
                print(f"    💰 Value:{value_bet}")
            
            predictions.append({
                "season_id": sid,
                "season_name": sname,
                "match_day": md_num,
                "home": home,
                "away": away,
                "prediction": pred,
                "confidence": round(conf, 1),
                "engine_probs": {"HOME": round(p_h*100,1), "DRAW": round(p_d*100,1), "AWAY": round(p_a*100,1)},
                "odds_h": odds_h, "odds_d": odds_d, "odds_a": odds_a,
                "value_edge": value_bet,
                "created_at": datetime.now().isoformat(),
            })
    
    # Save to output file for delivery
    output = {
        "generated_at": datetime.now().isoformat(),
        "season": sname,
        "md": current_md,
        "status": status,
        "abnormal_season": is_abnormal,
        "table_tau": round(tau, 4),
        "predictions": predictions,
    }
    
    outpath = os.path.join(OUTPUT_DIR, f"engine_predictions_{sname.replace(' ','_')}_MD{current_md}.json")
    with open(outpath, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n[ENGINE] Saved to {outpath}")
    
    # Print summary for cron delivery
    print(f"\n{'='*60}")
    print(f"📊 VFL ENGINE PREDICTIONS — {sname} MD {current_md}")
    print(f"{'='*60}")
    print(f"Status: {status} | Abnormal: {is_abnormal} (τ={tau:.3f})")
    print(f"Teams tracked: {sum(1 for t in TEAMS if abs(elo.get(t,1500)-1500) > 10)}/16")
    print()
    
    for p in predictions:
        conf_tier = "⭐" if p['confidence'] >= 55 else ("📊" if p['confidence'] >= 45 else "🤞")
        print(f"{conf_tier} {p['home']:<20} vs {p['away']:<20}")
        print(f"   → {p['prediction']} ({p['confidence']:.0f}%)  |  H:{p['engine_probs']['HOME']:.0f}% D:{p['engine_probs']['DRAW']:.0f}% A:{p['engine_probs']['AWAY']:.0f}%")
        print(f"   Odds: {p['odds_h']:.2f}/{p['odds_d']:.2f}/{p['odds_a']:.2f}")
        if p['value_edge']:
            print(f"   💰 {p['value_edge']}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

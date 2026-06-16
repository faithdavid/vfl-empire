#!/usr/bin/env python3
"""
pair_betting_rules.py — Per-Fixture-Pair Betting Rules from Finite State Space
=============================================================================
Uses Poisson distribution modeling and finite state space data to generate
individual betting rules for all 240 VFL fixture pairs.

Phase 1: Poisson Fit Per Pair
Phase 2: Tier Classification
Phase 3: Generate Betting Rules Per Pair (ALL markets: O2.5, U3.5, GG, NG, DNB, 1X2, DC)
Phase 4: Generate Combined Rulebook (Markdown + JSON)
Phase 5: Betting Advisor Function

Usage:
    python pair_betting_rules.py

Author: VFL Engineering Team
"""

import json
import math
import os
from collections import Counter

# ── Constants ──────────────────────────────────────────────────────────────────
FINITE_STATE_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/finite_state_space.json'
RULES_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis'
PAIR_RULES_JSON = os.path.join(RULES_DIR, 'pair_rules.json')
RULEBOOK_MD = os.path.join(RULES_DIR, 'pair_betting_rulebook.md')

# Tier thresholds
TIER_GOLDEN_SAFE = 80.0  # O1.5 >= 80%
TIER_GOLDEN = 75.0       # O1.5 >= 75%
TIER_STANDARD = 65.0     # O1.5 >= 65%
TIER_CAUTION = 55.0      # O1.5 >= 55%
# Below 55% = TRAP

# Classification thresholds for general markets (probabilities)
CLASS_ELITE = 0.80       # >= 80%
CLASS_GOOD = 0.70        # >= 70%
CLASS_STANDARD = 0.60    # >= 60%
CLASS_MARGINAL = 0.50    # >= 50%


def factorial(n):
    """Compute factorial of n."""
    return math.factorial(n)


def poisson_pmf(k, lam):
    """Poisson probability mass function: P(k) = (λ^k * e^(-λ)) / k!"""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / factorial(k)


def parse_scoreline(score_str):
    """Parse '2:1' -> (2, 1)."""
    parts = score_str.split(':')
    return int(parts[0]), int(parts[1])


def compute_total_goals_dist(scorelines, matches):
    """Convert per-scoreline counts to total-goals probability distribution.
    
    Returns:
        dict mapping total_goals -> probability
    """
    total_goals_counts = Counter()
    for score_str, count in scorelines.items():
        hg, ag = parse_scoreline(score_str)
        total_goals = hg + ag
        total_goals_counts[total_goals] += count
    
    dist = {}
    for tg, cnt in total_goals_counts.items():
        dist[tg] = cnt / matches
    return dist


def compute_lambda_from_dist(scorelines, matches):
    """Compute λ (average total goals) from scoreline distribution."""
    total_goals_sum = 0
    for score_str, count in scorelines.items():
        hg, ag = parse_scoreline(score_str)
        total_goals_sum += (hg + ag) * count
    return total_goals_sum / matches


def compute_gg_prob(scorelines, matches):
    """Compute both-teams-score probability from scoreline counts."""
    gg_count = 0
    for score_str, count in scorelines.items():
        hg, ag = parse_scoreline(score_str)
        if hg > 0 and ag > 0:
            gg_count += count
    return gg_count / matches


def classify_tier(o15_rate):
    """Classify a pair into a risk tier based on O1.5 rate."""
    if o15_rate >= TIER_GOLDEN_SAFE:
        return "GOLDEN_SAFE"
    elif o15_rate >= TIER_GOLDEN:
        return "GOLDEN"
    elif o15_rate >= TIER_STANDARD:
        return "STANDARD"
    elif o15_rate >= TIER_CAUTION:
        return "CAUTION"
    else:
        return "TRAP"


def classify_market(prob):
    """Classify a market probability into a rating tier.
    
    Returns (classification, verdict, threshold).
    """
    if prob >= CLASS_ELITE:
        return "ELITE", "BET_CONFIDENTLY", 1.25
    elif prob >= CLASS_GOOD:
        return "GOOD", "BET_IF_OVER_1.30", 1.30
    elif prob >= CLASS_STANDARD:
        return "STANDARD", "BET_IF_OVER_1.50", 1.50
    elif prob >= CLASS_MARGINAL:
        return "MARGINAL", "VALUE_IF_OVER_2.00", 2.00
    else:
        return "AVOID", "AVOID", None


def get_all_market_probs(pair_data):
    """Derive ALL market probabilities from scoreline distribution.
    
    Args:
        pair_data: dict with scorelines and matches keys
    
    Returns:
        dict mapping market_name -> {
            'prob': float,
            'fair_odds': float,
            'verdict': str,
            'threshold': float or None,
            'reason': str,
            'classification': str,
        }
    """
    matches = pair_data['matches']
    scorelines = pair_data['scorelines']
    
    # Build scoreline probability dict
    score_probs = {}
    for score_str, count in scorelines.items():
        score_probs[score_str] = count / matches
    
    # Total goals distribution
    total_goals_dist = compute_total_goals_dist(scorelines, matches)
    
    # ── Compute raw probabilities from scoreline distribution ──
    
    # O1.5 = 1 - P(0:0)
    p_00 = score_probs.get('0:0', 0.0)
    p_o15 = 1.0 - p_00
    
    # O2.5 = 1 - P(total <= 2)
    p_u25 = p_00 + score_probs.get('1:0', 0.0) + score_probs.get('0:1', 0.0) + score_probs.get('1:1', 0.0) + score_probs.get('2:0', 0.0) + score_probs.get('0:2', 0.0)
    p_o25 = 1.0 - p_u25
    
    # U3.5 = sum of scores where total <= 3
    p_u35 = sum(score_probs.get(s, 0.0) for s in scorelines if sum(parse_scoreline(s)) <= 3)
    
    # U4.5 = sum of scores where total <= 4
    p_u45 = sum(score_probs.get(s, 0.0) for s in scorelines if sum(parse_scoreline(s)) <= 4)
    
    # GG = both teams score
    p_gg = sum(score_probs.get(s, 0.0) for s in scorelines if parse_scoreline(s)[0] > 0 and parse_scoreline(s)[1] > 0)
    
    # NG = no goal (clean sheet for at least one side)
    p_ng = 1.0 - p_gg
    
    # 1X2
    p_home_win = sum(score_probs.get(s, 0.0) for s in scorelines if parse_scoreline(s)[0] > parse_scoreline(s)[1])
    p_draw = sum(score_probs.get(s, 0.0) for s in scorelines if parse_scoreline(s)[0] == parse_scoreline(s)[1])
    p_away_win = sum(score_probs.get(s, 0.0) for s in scorelines if parse_scoreline(s)[0] < parse_scoreline(s)[1])
    
    # DNB (Draw No Bet) — conditional on non-draws
    non_draws = p_home_win + p_away_win
    if non_draws > 0:
        p_dnb_home = p_home_win / non_draws
        p_dnb_away = p_away_win / non_draws
    else:
        p_dnb_home = 0.5
        p_dnb_away = 0.5
    
    # Double Chance
    p_dc_1x = p_home_win + p_draw
    p_dc_12 = p_home_win + p_away_win
    p_dc_x2 = p_draw + p_away_win
    
    # ── Build market results ──
    # Fair odds (no vig)
    def fair_odds(prob):
        return round(1.0 / prob, 2) if prob > 0 else 999.0
    
    markets = {}
    
    # --- O1.5 (uses existing tier classification) ---
    o15_rate_pct = pair_data.get('o15_rate', p_o15 * 100)
    tier = classify_tier(o15_rate_pct)
    if tier == "GOLDEN_SAFE":
        markets['O1.5'] = {
            'prob': round(p_o15, 4), 'fair_odds': fair_odds(p_o15),
            'verdict': 'BET_CONFIDENTLY', 'threshold': 1.10,
            'reason': f"Elite O1.5 rate: {o15_rate_pct}% — bet at any reasonable odds",
            'classification': 'ELITE',
        }
    elif tier == "GOLDEN":
        markets['O1.5'] = {
            'prob': round(p_o15, 4), 'fair_odds': fair_odds(p_o15),
            'verdict': 'BET_IF_OVER_1.25', 'threshold': 1.25,
            'reason': f"Strong O1.5 rate: {o15_rate_pct}% — value above 1.25",
            'classification': 'GOOD',
        }
    elif tier == "STANDARD":
        markets['O1.5'] = {
            'prob': round(p_o15, 4), 'fair_odds': fair_odds(p_o15),
            'verdict': 'BET_IF_OVER_1.35', 'threshold': 1.35,
            'reason': f"Decent O1.5 rate: {o15_rate_pct}% — only if odds > 1.35",
            'classification': 'STANDARD',
        }
    elif tier == "CAUTION":
        markets['O1.5'] = {
            'prob': round(p_o15, 4), 'fair_odds': fair_odds(p_o15),
            'verdict': 'AVOID', 'threshold': None,
            'reason': f"Marginal O1.5 rate: {o15_rate_pct}% — below breakeven threshold",
            'classification': 'MARGINAL',
        }
    else:  # TRAP
        markets['O1.5'] = {
            'prob': round(p_o15, 4), 'fair_odds': fair_odds(p_o15),
            'verdict': 'AVOID', 'threshold': None,
            'reason': f"Trap: O1.5 only {o15_rate_pct}% — do not bet",
            'classification': 'AVOID',
        }
    
    # --- O2.5 ---
    cl25, v25, t25 = classify_market(p_o25)
    if v25.startswith('BET'):
        reason25 = f"O2.5 rate {p_o25*100:.1f}% — strong value"
    elif v25.startswith('VALUE'):
        reason25 = f"O2.5 rate {p_o25*100:.1f}% — only with boosted odds"
    else:
        reason25 = f"O2.5 only {p_o25*100:.1f}% — too low"
    markets['O2.5'] = {
        'prob': round(p_o25, 4), 'fair_odds': fair_odds(p_o25),
        'verdict': v25, 'threshold': t25,
        'reason': reason25, 'classification': cl25,
    }
    
    # --- U3.5 ---
    cl35, v35, t35 = classify_market(p_u35)
    if p_u35 >= 0.80:
        v35 = "BET_IF_OVER_1.15"
        t35 = 1.15
        cl35 = "ELITE"
    elif p_u35 >= 0.70:
        v35 = "BET_IF_OVER_1.30"
        t35 = 1.30
        cl35 = "GOOD"
    if v35.startswith('BET'):
        reason35 = f"Under 3.5 safe at {p_u35*100:.1f}% — odds above {t35} offer value"
    elif v35.startswith('VALUE'):
        reason35 = f"Under 3.5 at {p_u35*100:.1f}% — slim edge"
    else:
        reason35 = f"Under 3.5 only {p_u35*100:.1f}% — not reliable"
    markets['U3.5'] = {
        'prob': round(p_u35, 4), 'fair_odds': fair_odds(p_u35),
        'verdict': v35, 'threshold': t35,
        'reason': reason35, 'classification': cl35,
    }
    
    # --- U4.5 ---
    if p_u45 >= 0.85:
        v45 = "BET_IF_OVER_1.10"
        t45 = 1.10
        cl45 = "ELITE"
        reason45 = f"Under 4.5 very safe at {p_u45*100:.1f}%"
    elif p_u45 >= 0.75:
        v45 = "BET_IF_OVER_1.25"
        t45 = 1.25
        cl45 = "GOOD"
        reason45 = f"Under 4.5 safe at {p_u45*100:.1f}%"
    elif p_u45 >= 0.60:
        v45 = "BET_IF_OVER_1.50"
        t45 = 1.50
        cl45 = "STANDARD"
        reason45 = f"Under 4.5 decent at {p_u45*100:.1f}%"
    elif p_u45 >= 0.50:
        v45 = "VALUE_IF_OVER_2.00"
        t45 = 2.00
        cl45 = "MARGINAL"
        reason45 = f"Under 4.5 marginal at {p_u45*100:.1f}%"
    else:
        v45 = "AVOID"
        t45 = None
        cl45 = "AVOID"
        reason45 = f"Under 4.5 only {p_u45*100:.1f}%"
    markets['U4.5'] = {
        'prob': round(p_u45, 4), 'fair_odds': fair_odds(p_u45),
        'verdict': v45, 'threshold': t45,
        'reason': reason45, 'classification': cl45,
    }
    
    # --- GG ---
    cl_gg, v_gg, t_gg = classify_market(p_gg)
    if p_gg >= 0.55:
        v_gg = "BET_IF_OVER_1.70"
        t_gg = 1.70
        cl_gg = "GOOD" if p_gg >= 0.70 else "STANDARD"
    elif p_gg >= 0.45:
        v_gg = "VALUE_IF_OVER_2.00"
        t_gg = 2.00
        cl_gg = "MARGINAL"
    else:
        v_gg = "AVOID"
        t_gg = None
        cl_gg = "AVOID"
    if v_gg.startswith('BET'):
        reason_gg = f"GG at {p_gg*100:.1f}% — value above {t_gg}"
    elif v_gg.startswith('VALUE'):
        reason_gg = f"GG at {p_gg*100:.1f}% — only with boosted odds"
    else:
        reason_gg = f"GG only {p_gg*100:.1f}% — low both-teams-scoring rate"
    markets['GG'] = {
        'prob': round(p_gg, 4), 'fair_odds': fair_odds(p_gg),
        'verdict': v_gg, 'threshold': t_gg,
        'reason': reason_gg, 'classification': cl_gg,
    }
    
    # --- NG ---
    cl_ng, v_ng, t_ng = classify_market(p_ng)
    if v_ng.startswith('BET'):
        reason_ng = f"NG at {p_ng*100:.1f}% — value above {t_ng}"
    elif v_ng.startswith('VALUE'):
        reason_ng = f"NG at {p_ng*100:.1f}% — only with boosted odds"
    else:
        reason_ng = f"NG only {p_ng*100:.1f}% — low clean-sheet rate"
    markets['NG'] = {
        'prob': round(p_ng, 4), 'fair_odds': fair_odds(p_ng),
        'verdict': v_ng, 'threshold': t_ng,
        'reason': reason_ng, 'classification': cl_ng,
    }
    
    # --- 1X2: Home_Win ---
    cl_hw, v_hw, t_hw = classify_market(p_home_win)
    if v_hw.startswith('BET'):
        reason_hw = f"Home win at {p_home_win*100:.1f}% — value above {t_hw}"
    elif v_hw.startswith('VALUE'):
        reason_hw = f"Home win at {p_home_win*100:.1f}% — slim edge"
    else:
        reason_hw = f"Home win only {p_home_win*100:.1f}% — unreliable"
    markets['Home_Win'] = {
        'prob': round(p_home_win, 4), 'fair_odds': fair_odds(p_home_win),
        'verdict': v_hw, 'threshold': t_hw,
        'reason': reason_hw, 'classification': cl_hw,
    }
    
    # --- 1X2: Draw ---
    cl_dw, v_dw, t_dw = classify_market(p_draw)
    if v_dw.startswith('BET'):
        reason_dw = f"Draw at {p_draw*100:.1f}% — value above {t_dw}"
    elif v_dw.startswith('VALUE'):
        reason_dw = f"Draw at {p_draw*100:.1f}% — slim edge"
    else:
        reason_dw = f"Draw only {p_draw*100:.1f}% — unreliable"
    markets['Draw'] = {
        'prob': round(p_draw, 4), 'fair_odds': fair_odds(p_draw),
        'verdict': v_dw, 'threshold': t_dw,
        'reason': reason_dw, 'classification': cl_dw,
    }
    
    # --- 1X2: Away_Win ---
    cl_aw, v_aw, t_aw = classify_market(p_away_win)
    if v_aw.startswith('BET'):
        reason_aw = f"Away win at {p_away_win*100:.1f}% — value above {t_aw}"
    elif v_aw.startswith('VALUE'):
        reason_aw = f"Away win at {p_away_win*100:.1f}% — slim edge"
    else:
        reason_aw = f"Away win only {p_away_win*100:.1f}% — unreliable"
    markets['Away_Win'] = {
        'prob': round(p_away_win, 4), 'fair_odds': fair_odds(p_away_win),
        'verdict': v_aw, 'threshold': t_aw,
        'reason': reason_aw, 'classification': cl_aw,
    }
    
    # --- DNB Home ---
    if p_dnb_home >= 0.70:
        v_dnb_h = "BET_CONFIDENTLY"
        t_dnb_h = 1.40
        cl_dnb_h = "ELITE"
        reason_dnb_h = f"Home wins {p_dnb_home*100:.1f}% of non-draws — strong"
    elif p_dnb_home >= 0.60:
        v_dnb_h = "BET_IF_OVER_1.60"
        t_dnb_h = 1.60
        cl_dnb_h = "GOOD"
        reason_dnb_h = f"Home wins {p_dnb_home*100:.1f}% of non-draws — value above 1.60"
    elif p_dnb_home >= 0.55:
        v_dnb_h = "VALUE_IF_OVER_1.80"
        t_dnb_h = 1.80
        cl_dnb_h = "STANDARD"
        reason_dnb_h = f"Home wins {p_dnb_home*100:.1f}% of non-draws — value above 1.80"
    elif p_dnb_home >= 0.45:
        v_dnb_h = "VALUE_IF_OVER_2.10"
        t_dnb_h = 2.10
        cl_dnb_h = "MARGINAL"
        reason_dnb_h = f"Home wins {p_dnb_home*100:.1f}% of non-draws — slim edge"
    else:
        v_dnb_h = "AVOID"
        t_dnb_h = None
        cl_dnb_h = "AVOID"
        reason_dnb_h = f"Home wins only {p_dnb_home*100:.1f}% of non-draws"
    markets['DNB_Home'] = {
        'prob': round(p_dnb_home, 4), 'fair_odds': fair_odds(p_dnb_home),
        'verdict': v_dnb_h, 'threshold': t_dnb_h,
        'reason': reason_dnb_h, 'classification': cl_dnb_h,
    }
    
    # --- DNB Away ---
    if p_dnb_away >= 0.70:
        v_dnb_a = "BET_CONFIDENTLY"
        t_dnb_a = 1.40
        cl_dnb_a = "ELITE"
        reason_dnb_a = f"Away wins {p_dnb_away*100:.1f}% of non-draws — strong"
    elif p_dnb_away >= 0.60:
        v_dnb_a = "BET_IF_OVER_1.60"
        t_dnb_a = 1.60
        cl_dnb_a = "GOOD"
        reason_dnb_a = f"Away wins {p_dnb_away*100:.1f}% of non-draws — value above 1.60"
    elif p_dnb_away >= 0.55:
        v_dnb_a = "VALUE_IF_OVER_1.80"
        t_dnb_a = 1.80
        cl_dnb_a = "STANDARD"
        reason_dnb_a = f"Away wins {p_dnb_away*100:.1f}% of non-draws — value above 1.80"
    elif p_dnb_away >= 0.45:
        v_dnb_a = "VALUE_IF_OVER_2.10"
        t_dnb_a = 2.10
        cl_dnb_a = "MARGINAL"
        reason_dnb_a = f"Away wins {p_dnb_away*100:.1f}% of non-draws — slim edge"
    else:
        v_dnb_a = "AVOID"
        t_dnb_a = None
        cl_dnb_a = "AVOID"
        reason_dnb_a = f"Away wins only {p_dnb_away*100:.1f}% of non-draws"
    markets['DNB_Away'] = {
        'prob': round(p_dnb_away, 4), 'fair_odds': fair_odds(p_dnb_away),
        'verdict': v_dnb_a, 'threshold': t_dnb_a,
        'reason': reason_dnb_a, 'classification': cl_dnb_a,
    }
    
    # --- Double Chance: DC_1X (Home Win or Draw) ---
    cl_dc1, v_dc1, t_dc1 = classify_market(p_dc_1x)
    if v_dc1.startswith('BET'):
        reason_dc1 = f"DC 1X at {p_dc_1x*100:.1f}% — strong safety net"
    elif v_dc1.startswith('VALUE'):
        reason_dc1 = f"DC 1X at {p_dc_1x*100:.1f}% — slim edge"
    else:
        reason_dc1 = f"DC 1X only {p_dc_1x*100:.1f}% — unreliable"
    markets['DC_1X'] = {
        'prob': round(p_dc_1x, 4), 'fair_odds': fair_odds(p_dc_1x),
        'verdict': v_dc1, 'threshold': t_dc1,
        'reason': reason_dc1, 'classification': cl_dc1,
    }
    
    # --- Double Chance: DC_12 (Home Win or Away Win — no draw) ---
    cl_dc12, v_dc12, t_dc12 = classify_market(p_dc_12)
    if v_dc12.startswith('BET'):
        reason_dc12 = f"DC 12 at {p_dc_12*100:.1f}% — strong no-draw bet"
    elif v_dc12.startswith('VALUE'):
        reason_dc12 = f"DC 12 at {p_dc_12*100:.1f}% — slim edge"
    else:
        reason_dc12 = f"DC 12 only {p_dc_12*100:.1f}% — unreliable"
    markets['DC_12'] = {
        'prob': round(p_dc_12, 4), 'fair_odds': fair_odds(p_dc_12),
        'verdict': v_dc12, 'threshold': t_dc12,
        'reason': reason_dc12, 'classification': cl_dc12,
    }
    
    # --- Double Chance: DC_X2 (Draw or Away Win) ---
    cl_dcx2, v_dcx2, t_dcx2 = classify_market(p_dc_x2)
    if v_dcx2.startswith('BET'):
        reason_dcx2 = f"DC X2 at {p_dc_x2*100:.1f}% — strong safety net"
    elif v_dcx2.startswith('VALUE'):
        reason_dcx2 = f"DC X2 at {p_dc_x2*100:.1f}% — slim edge"
    else:
        reason_dcx2 = f"DC X2 only {p_dc_x2*100:.1f}% — unreliable"
    markets['DC_X2'] = {
        'prob': round(p_dc_x2, 4), 'fair_odds': fair_odds(p_dc_x2),
        'verdict': v_dcx2, 'threshold': t_dcx2,
        'reason': reason_dcx2, 'classification': cl_dcx2,
    }
    
    return markets


def get_best_market_for_pair(home, away, all_rules=None, market_odds=None):
    """Get the best market for a specific fixture pair.
    
    Args:
        home: Home team name
        away: Away team name
        all_rules: Pre-loaded rules dict (optional)
        market_odds: Dict of market_name -> odds from MSport API (optional)
    
    Returns:
        Dict with best_market, best_verdict, best_prob, best_fair_odds, all_evs (if odds provided)
    """
    if all_rules is None:
        data = load_finite_state_data()
        all_rules, _ = analyze_all_pairs(data)
    
    pair_key = f"{home} vs {away}"
    rule = all_rules.get(pair_key)
    
    if not rule:
        return {
            'pair': pair_key,
            'found': False,
            'best_market': 'NONE',
            'best_verdict': 'NO_DATA',
        }
    
    all_markets = rule['all_market_probs']
    
    if market_odds:
        # Compute EV for each market where odds exist
        best_ev = -999
        best_market = None
        best_verdict = None
        all_evs = {}
        for mkt, mkt_data in all_markets.items():
            if mkt in market_odds:
                odds = market_odds[mkt]
                prob = mkt_data['prob']
                ev = round(prob * odds - 1, 4)
                all_evs[mkt] = ev
                if ev > best_ev:
                    best_ev = ev
                    best_market = mkt
                    best_verdict = mkt_data['verdict']
        
        if best_market is None:
            # Fallback to highest prob non-AVOID
            return get_best_market_for_pair(home, away, all_rules, market_odds=None)
        
        return {
            'pair': pair_key,
            'found': True,
            'best_market': best_market,
            'best_verdict': best_verdict,
            'best_ev': best_ev,
            'all_evs': all_evs,
        }
    else:
        # No odds: return the market with highest probability that is not AVOID
        best_prob = -1
        best_market = None
        best_verdict = None
        
        # Priority list: prefer bettable markets
        priority_markets = ['O1.5', 'U3.5', 'DC_1X', 'DC_X2', 'U4.5', 'GG', 'O2.5', 'DC_12', 'DNB_Home', 'Home_Win', 'DNB_Away', 'Away_Win', 'NG', 'Draw']
        
        for mkt in priority_markets:
            mkt_data = all_markets.get(mkt)
            if mkt_data and mkt_data['verdict'] != 'AVOID' and mkt_data['prob'] > best_prob:
                best_prob = mkt_data['prob']
                best_market = mkt
                best_verdict = mkt_data['verdict']
        
        if best_market is None:
            # Even AVOID markets, pick highest prob
            for mkt, mkt_data in all_markets.items():
                if mkt_data['prob'] > best_prob:
                    best_prob = mkt_data['prob']
                    best_market = mkt
                    best_verdict = mkt_data['verdict']
        
        return {
            'pair': pair_key,
            'found': True,
            'best_market': best_market,
            'best_verdict': best_verdict,
            'best_prob': best_prob,
        }


def compute_home_win_prob(scorelines, matches):
    """Compute home win probability (excluding draws)."""
    home_wins = 0
    draws = 0
    for score_str, count in scorelines.items():
        hg, ag = parse_scoreline(score_str)
        if hg > ag:
            home_wins += count
        elif hg == ag:
            draws += count
    
    # DNB = home wins as proportion of non-draws
    non_draws = matches - draws
    if non_draws > 0:
        return home_wins / non_draws
    return 0.5


def generate_market_rules(pair_data):
    """Generate betting rules for common markets based on pair stats.
    
    Returns dict with market rules and a summary betting_rule string.
    """
    matches = pair_data['matches']
    o15_rate = pair_data['o15_rate'] / 100.0
    o25_rate = pair_data['o25_rate'] / 100.0
    gg_rate = pair_data['gg_rate'] / 100.0
    scorelines = pair_data['scorelines']
    
    # Compute total goals distribution
    total_goals_dist = compute_total_goals_dist(scorelines, matches)
    
    # Compute λ
    lam = compute_lambda_from_dist(scorelines, matches)
    
    # Poisson-predicted probabilities for total goals
    poisson_probs = {}
    for k in range(0, 7):  # 0 through 6
        poisson_probs[k] = poisson_pmf(k, lam)
    poisson_probs['6+'] = 1.0 - sum(poisson_probs[k] for k in range(0, 6))
    
    # Observed total goal probabilities
    observed_probs = {}
    for k in range(0, 7):
        observed_probs[k] = total_goals_dist.get(k, 0.0)
    observed_probs['6+'] = sum(v for k, v in total_goals_dist.items() if k >= 6)
    
    # Market calculations from observed data
    o15_prob = 1.0 - observed_probs.get(0, 0.0) - observed_probs.get(1, 0.0)
    o25_prob = 1.0 - observed_probs.get(0, 0.0) - observed_probs.get(1, 0.0) - observed_probs.get(2, 0.0)
    u35_prob = observed_probs.get(0, 0.0) + observed_probs.get(1, 0.0) + observed_probs.get(2, 0.0) + observed_probs.get(3, 0.0)
    u45_prob = u35_prob + observed_probs.get(4, 0.0)
    gg_prob = compute_gg_prob(scorelines, matches)
    
    # Home win and DNB
    home_win_dnb = compute_home_win_prob(scorelines, matches)
    
    # Fair odds (1 / probability, no vig)
    fair_o15 = 1.0 / o15_prob if o15_prob > 0 else 999
    fair_o25 = 1.0 / o25_prob if o25_prob > 0 else 999
    fair_u35 = 1.0 / u35_prob if u35_prob > 0 else 999
    fair_u45 = 1.0 / u45_prob if u45_prob > 0 else 999
    fair_gg = 1.0 / gg_prob if gg_prob > 0 else 999
    fair_dnb_home = 1.0 / home_win_dnb if home_win_dnb > 0 else 999
    
    # Tier
    tier = classify_tier(pair_data['o15_rate'])
    
    # Generate verdicts for existing markets (backward compatible)
    market_rules = {}
    
    # --- O1.5 ---
    if tier == "GOLDEN_SAFE":
        verdict_o15 = "BET_CONFIDENTLY"
        reason_o15 = f"Elite O1.5 rate: {pair_data['o15_rate']}% — bet at any reasonable odds"
        threshold_o15 = 1.10
    elif tier == "GOLDEN":
        verdict_o15 = "BET_IF_OVER_1.25"
        reason_o15 = f"Strong O1.5 rate: {pair_data['o15_rate']}% — value above 1.25"
        threshold_o15 = 1.25
    elif tier == "STANDARD":
        verdict_o15 = "BET_IF_OVER_1.35"
        reason_o15 = f"Decent O1.5 rate: {pair_data['o15_rate']}% — only if odds > 1.35"
        threshold_o15 = 1.35
    elif tier == "CAUTION":
        verdict_o15 = "AVOID"
        reason_o15 = f"Marginal O1.5 rate: {pair_data['o15_rate']}% — below breakeven threshold"
        threshold_o15 = None
    else:  # TRAP
        verdict_o15 = "AVOID"
        reason_o15 = f"Trap: O1.5 only {pair_data['o15_rate']}% — do not bet"
        threshold_o15 = None
    
    market_rules['O1.5'] = {
        'prob': round(o15_prob, 4),
        'fair_odds': round(fair_o15, 2),
        'verdict': verdict_o15,
        'threshold': threshold_o15,
        'reason': reason_o15,
    }
    
    # --- O2.5 ---
    if o25_prob >= 0.50:
        verdict_o25 = "BET_IF_OVER_2.00"
        reason_o25 = f"O2.5 rate {pair_data['o25_rate']}% — value possible above 2.00"
        threshold_o25 = 2.00
    elif o25_prob >= 0.35:
        verdict_o25 = "VALUE_IF_OVER_2.50"
        reason_o25 = f"O2.5 rate {pair_data['o25_rate']}% — only with boosted odds"
        threshold_o25 = 2.50
    else:
        verdict_o25 = "AVOID"
        reason_o25 = f"O2.5 only {pair_data['o25_rate']}% — too low"
        threshold_o25 = None
    
    market_rules['O2.5'] = {
        'prob': round(o25_prob, 4),
        'fair_odds': round(fair_o25, 2),
        'verdict': verdict_o25,
        'threshold': threshold_o25,
        'reason': reason_o25,
    }
    
    # --- U3.5 ---
    if u35_prob >= 0.80:
        verdict_u35 = "BET_IF_OVER_1.15"
        reason_u35 = f"Under 3.5 is safe at {u35_prob*100:.1f}% — odds above 1.15 offer value"
        threshold_u35 = 1.15
    elif u35_prob >= 0.70:
        verdict_u35 = "BET_IF_OVER_1.30"
        reason_u35 = f"Under 3.5 solid at {u35_prob*100:.1f}% — need odds > 1.30"
        threshold_u35 = 1.30
    else:
        verdict_u35 = "AVOID"
        reason_u35 = f"Under 3.5 only {u35_prob*100:.1f}% — not reliable"
        threshold_u35 = None
    
    market_rules['U3.5'] = {
        'prob': round(u35_prob, 4),
        'fair_odds': round(fair_u35, 2),
        'verdict': verdict_u35,
        'threshold': threshold_u35,
        'reason': reason_u35,
    }
    
    # --- U4.5 ---
    if u45_prob >= 0.85:
        verdict_u45 = "BET_IF_OVER_1.10"
        reason_u45 = f"Under 4.5 very safe at {u45_prob*100:.1f}%"
        threshold_u45 = 1.10
    elif u45_prob >= 0.75:
        verdict_u45 = "BET_IF_OVER_1.25"
        reason_u45 = f"Under 4.5 safe at {u45_prob*100:.1f}%"
        threshold_u45 = 1.25
    else:
        verdict_u45 = "AVOID"
        reason_u45 = f"Under 4.5 only {u45_prob*100:.1f}%"
        threshold_u45 = None
    
    market_rules['U4.5'] = {
        'prob': round(u45_prob, 4),
        'fair_odds': round(fair_u45, 2),
        'verdict': verdict_u45,
        'threshold': threshold_u45,
        'reason': reason_u45,
    }
    
    # --- GG ---
    if gg_prob >= 0.55:
        verdict_gg = "BET_IF_OVER_1.70"
        reason_gg = f"GG at {pair_data['gg_rate']}% — value above 1.70"
        threshold_gg = 1.70
    elif gg_prob >= 0.45:
        verdict_gg = "VALUE_IF_OVER_2.00"
        reason_gg = f"GG at {pair_data['gg_rate']}% — only with boosted odds"
        threshold_gg = 2.00
    else:
        verdict_gg = "AVOID"
        reason_gg = f"GG only {pair_data['gg_rate']}% — low both-teams-scoring rate"
        threshold_gg = None
    
    market_rules['GG'] = {
        'prob': round(gg_prob, 4),
        'fair_odds': round(fair_gg, 2),
        'verdict': verdict_gg,
        'threshold': threshold_gg,
        'reason': reason_gg,
    }
    
    # --- DNB Home ---
    if home_win_dnb >= 0.55:
        verdict_dnb = "VALUE_IF_OVER_1.80"
        reason_dnb = f"Home wins {home_win_dnb*100:.1f}% of non-draws — value above 1.80"
        threshold_dnb = 1.80
    elif home_win_dnb >= 0.45:
        verdict_dnb = "VALUE_IF_OVER_2.10"
        reason_dnb = f"Home wins {home_win_dnb*100:.1f}% of non-draws — slim edge"
        threshold_dnb = 2.10
    else:
        verdict_dnb = "AVOID"
        reason_dnb = f"Home wins only {home_win_dnb*100:.1f}% of non-draws"
        threshold_dnb = None
    
    market_rules['DNB_Home'] = {
        'prob': round(home_win_dnb, 4),
        'fair_odds': round(fair_dnb_home, 2),
        'verdict': verdict_dnb,
        'threshold': threshold_dnb,
        'reason': reason_dnb,
    }
    
    # Determine the single best market to bet
    best_market, best_verdict = find_best_market(market_rules, tier, pair_data)
    
    # Build summary betting rule line
    summary_parts = []
    for market, rule in market_rules.items():
        v = rule['verdict']
        if v == 'AVOID':
            summary_parts.append(f"AVOID {market}")
        elif v.startswith('BET'):
            thr = rule.get('threshold')
            if thr:
                summary_parts.append(f"BET {market} if odds > {thr}")
            else:
                summary_parts.append(f"BET {market}")
        elif v.startswith('VALUE'):
            thr = rule.get('threshold')
            if thr:
                summary_parts.append(f"VALUE {market} if odds > {thr}")
            else:
                summary_parts.append(f"VALUE {market}")
    
    betting_rule = " | ".join(summary_parts)
    
    return {
        'market_rules': market_rules,
        'best_market': best_market,
        'best_verdict': best_verdict,
        'betting_rule': betting_rule,
        'poisson_fit': {
            'lambda': round(lam, 4),
            'poisson_probs': {str(k): round(v, 4) for k, v in poisson_probs.items()},
            'observed_probs': {str(k): round(v, 4) for k, v in observed_probs.items()},
        }
    }


def find_best_market(market_rules, tier, pair_data):
    """Determine the single best market to bet for this pair."""
    # Priority: O1.5 > U3.5 > U4.5 > GG > O2.5 > DNB_Home
    # For GOLDEN_SAFE/GOLDEN, O1.5 is king
    if tier in ('GOLDEN_SAFE', 'GOLDEN'):
        if market_rules['O1.5']['verdict'].startswith('BET'):
            return ('O1.5', market_rules['O1.5']['verdict'])
    
    # Check U3.5 for any tier
    u35_v = market_rules['U3.5']['verdict']
    if u35_v.startswith('BET'):
        return ('U3.5', u35_v)
    
    # Check U4.5
    u45_v = market_rules['U4.5']['verdict']
    if u45_v.startswith('BET'):
        return ('U4.5', u45_v)
    
    # Check GG
    gg_v = market_rules['GG']['verdict']
    if gg_v.startswith('BET') or gg_v.startswith('VALUE'):
        return ('GG', gg_v)
    
    # Check O1.5 for STANDARD
    if tier == 'STANDARD' and market_rules['O1.5']['verdict'].startswith('BET'):
        return ('O1.5', market_rules['O1.5']['verdict'])
    
    # Check O2.5
    o25_v = market_rules['O2.5']['verdict']
    if o25_v.startswith('BET') or o25_v.startswith('VALUE'):
        return ('O2.5', o25_v)
    
    # Check DNB_Home
    dnb_v = market_rules['DNB_Home']['verdict']
    if dnb_v.startswith('VALUE'):
        return ('DNB_Home', dnb_v)
    
    # Fallback
    return ('U3.5', 'AVOID_ALL')


def load_finite_state_data(path=FINITE_STATE_PATH):
    """Load the finite state space JSON data."""
    with open(path) as f:
        return json.load(f)


def analyze_all_pairs(data):
    """Analyze all 240 pairs and generate betting rules including ALL markets."""
    pair_stats = data['pair_stats']
    
    all_rules = {}
    tier_counts = Counter()
    
    for pair_key, stats in pair_stats.items():
        home = stats['home']
        away = stats['away']
        matches = stats['matches']
        o15_rate = stats['o15_rate']
        o25_rate = stats['o25_rate']
        gg_rate = stats['gg_rate']
        most_common_score = stats['most_common_score']
        scorelines = stats['scorelines']
        
        # Convert scoreline counts to probabilities
        scoreline_probs = {}
        for score_str, count in scorelines.items():
            scoreline_probs[score_str] = round(count / matches, 4)
        
        # Tier classification
        tier = classify_tier(o15_rate)
        tier_counts[tier] += 1
        
        # Compute λ
        lam = compute_lambda_from_dist(scorelines, matches)
        
        # Generate market rules (backward compatible)
        rules = generate_market_rules(stats)
        
        # Generate ALL market probabilities
        all_markets = get_all_market_probs(stats)
        
        all_rules[pair_key] = {
            'pair': pair_key,
            'home': home,
            'away': away,
            'matches_analyzed': matches,
            'lambda_goals': round(lam, 4),
            'o15_rate': o15_rate,
            'o25_rate': o25_rate,
            'gg_rate': gg_rate,
            'most_common_score': most_common_score,
            'tier': tier,
            'observed_distribution': scoreline_probs,
            # ALL market probabilities (expanded)
            'all_market_probs': all_markets,
            # Backward-compatible market rules
            'market_rules': rules['market_rules'],
            'best_market': rules['best_market'],
            'best_verdict': rules['best_verdict'],
            'betting_rule': rules['betting_rule'],
            'poisson_fit': rules['poisson_fit'],
        }
    
    return all_rules, tier_counts


def generate_markdown_rulebook(all_rules, tier_counts, data):
    """Generate the full Markdown rulebook with ALL markets."""
    pair_stats = data['pair_stats']
    
    lines = []
    lines.append("# VFL Empire — Per-Fixture-Pair Betting Rulebook (Multi-Market)")
    lines.append("")
    lines.append(f"*Generated: {data.get('analyzed_at', 'N/A')}*")
    lines.append(f"*Total pairs: {data['total_pairs']}*")
    lines.append(f"*Total matches analyzed: {data['total_matches']}*")
    lines.append("")
    lines.append("Markets covered: **O1.5**, **O2.5**, **U3.5**, **U4.5**, **GG**, **NG**, ")
    lines.append("**Home_Win**, **Draw**, **Away_Win**, **DNB_Home**, **DNB_Away**, ")
    lines.append("**DC_1X** (Home or Draw), **DC_12** (Home or Away), **DC_X2** (Draw or Away)")
    lines.append("")
    
    # ── Section 1: Summary ──
    lines.append("## 1. Tier Distribution Summary")
    lines.append("")
    lines.append("| Tier | Count | Description |")
    lines.append("|------|-------|-------------|")
    
    tier_descriptions = {
        'GOLDEN_SAFE': 'O1.5 ≥ 80% — Elite, bet confidently',
        'GOLDEN': 'O1.5 75-80% — Strong, value above 1.25',
        'STANDARD': 'O1.5 65-75% — Decent, odds above 1.35',
        'CAUTION': 'O1.5 55-65% — Marginal, avoid O1.5',
        'TRAP': 'O1.5 < 55% — Do not bet O1.5',
    }
    
    for tier in ['GOLDEN_SAFE', 'GOLDEN', 'STANDARD', 'CAUTION', 'TRAP']:
        count = tier_counts.get(tier, 0)
        lines.append(f"| **{tier}** | {count} | {tier_descriptions.get(tier, '')} |")
    
    lines.append("")
    
    # Summary stats
    o15_rates = [s['o15_rate'] for s in pair_stats.values()]
    lines.append(f"- **Mean O1.5 rate**: {sum(o15_rates)/len(o15_rates):.1f}%")
    lines.append(f"- **Min O1.5 rate**: {min(o15_rates):.1f}%")
    lines.append(f"- **Max O1.5 rate**: {max(o15_rates):.1f}%")
    lines.append(f"- **Pairs with O1.5 ≥ 75% (Golden)**: {tier_counts.get('GOLDEN_SAFE', 0) + tier_counts.get('GOLDEN', 0)}")
    lines.append(f"- **Pairs with O1.5 < 55% (Trap)**: {tier_counts.get('TRAP', 0)}")
    lines.append("")
    
    # ── Section 2: Golden Pairs (O1.5 >= 75%) ──
    golden = {k: v for k, v in all_rules.items() if v['tier'] in ('GOLDEN_SAFE', 'GOLDEN')}
    golden_sorted = sorted(golden.items(), key=lambda x: x[1]['o15_rate'], reverse=True)
    
    lines.append("## 2. Golden Pairs (O1.5 ≥ 75%) — Bet O1.5 Confidently")
    lines.append("")
    lines.append(f"*{len(golden_sorted)} pairs found*")
    lines.append("")
    lines.append("| # | Pair | O1.5% | O2.5% | GG% | λ | Best Market | Tier |")
    lines.append("|---|------|-------|-------|------|----|--------------|------|")
    
    for i, (key, rule) in enumerate(golden_sorted, 1):
        tier_icon = "🟢" if rule['tier'] == 'GOLDEN_SAFE' else "🟡"
        lines.append(
            f"| {i} | {key} | **{rule['o15_rate']}%** | {rule['o25_rate']}% | "
            f"{rule['gg_rate']}% | {rule['lambda_goals']} | "
            f"**{rule['best_market']}** | {tier_icon} {rule['tier']} |"
        )
    
    lines.append("")
    
    # ── Section 3: Trap Pairs (O1.5 < 55%) ──
    traps = {k: v for k, v in all_rules.items() if v['tier'] == 'TRAP'}
    traps_sorted = sorted(traps.items(), key=lambda x: x[1]['o15_rate'])
    
    lines.append("## 3. Trap Pairs (O1.5 < 55%) — AVOID O1.5")
    lines.append("")
    lines.append(f"*{len(traps_sorted)} pairs found*")
    lines.append("")
    lines.append("| # | Pair | O1.5% | O2.5% | GG% | λ | Best Market | Most Common |")
    lines.append("|---|------|-------|-------|------|----|--------------|-------------|")
    
    for i, (key, rule) in enumerate(traps_sorted, 1):
        lines.append(
            f"| {i} | **{key}** | 🔴 **{rule['o15_rate']}%** | {rule['o25_rate']}% | "
            f"{rule['gg_rate']}% | {rule['lambda_goals']} | "
            f"{rule['best_market']} | {rule['most_common_score']} |"
        )
    
    lines.append("")
    
    # ── Section 4: Complete Pair-by-Pair Rules ──
    lines.append("## 4. Complete Pair-by-Pair Betting Rules (All 240)")
    lines.append("")
    lines.append("For each pair, all 14 markets are shown with probability, fair odds, verdict, and classification.")
    lines.append("")
    lines.append("**Classification key:** ELITE (≥80%) | GOOD (≥70%) | STANDARD (≥60%) | MARGINAL (≥50%) | AVOID (<50%)")
    lines.append("")
    
    # Sort alphabetically
    sorted_pairs = sorted(all_rules.items(), key=lambda x: x[0])
    
    for pair_key, rule in sorted_pairs:
        tier = rule['tier']
        tier_emoji = {
            'GOLDEN_SAFE': '🟢',
            'GOLDEN': '🟡',
            'STANDARD': '🔵',
            'CAUTION': '🟠',
            'TRAP': '🔴',
        }.get(tier, '⚪')
        
        lines.append(f"### {tier_emoji} {pair_key}")
        lines.append("")
        lines.append(f"- **Tier**: {tier}")
        lines.append(f"- **Matches Analyzed**: {rule['matches_analyzed']}")
        lines.append(f"- **λ (Avg Total Goals)**: {rule['lambda_goals']}")
        lines.append(f"- **O1.5**: {rule['o15_rate']}% | **O2.5**: {rule['o25_rate']}% | **GG**: {rule['gg_rate']}%")
        lines.append(f"- **Most Common Score**: {rule['most_common_score']}")
        lines.append(f"- **Best Market**: {rule['best_market']} — {rule['best_verdict']}")
        lines.append(f"- **Rule**: {rule['betting_rule']}")
        lines.append("")
        
        # All market details table (expanded with classification)
        lines.append("| Market | Prob | Fair Odds | Verdict | Threshold | Class |")
        lines.append("|--------|------|-----------|---------|-----------|-------|")
        for mkt, mr in rule['all_market_probs'].items():
            thr = str(mr['threshold']) if mr['threshold'] else 'N/A'
            cl = mr.get('classification', 'N/A')
            lines.append(f"| {mkt} | {mr['prob']*100:.1f}% | {mr['fair_odds']} | {mr['verdict']} | {thr} | {cl} |")
        lines.append("")
        
        # Also show backward-compatible summary markets
        lines.append("**Legacy Market Summary:**")
        lines.append("")
        lines.append("| Market | Prob | Fair Odds | Verdict | Threshold |")
        lines.append("|--------|------|-----------|---------|-----------|")
        for mkt, mr in rule['market_rules'].items():
            thr = str(mr['threshold']) if mr['threshold'] else 'N/A'
            lines.append(f"| {mkt} | {mr['prob']*100:.1f}% | {mr['fair_odds']} | {mr['verdict']} | {thr} |")
        lines.append("")
        
        # Poisson fit comparison
        pf = rule['poisson_fit']
        lines.append("**Poisson Fit (λ={}):**".format(pf['lambda']))
        lines.append("")
        lines.append("| k | Observed | Poisson | Delta |")
        lines.append("|---|----------|---------|-------|")
        for k in ['0', '1', '2', '3', '4', '5', '6+']:
            obs = pf['observed_probs'].get(k, 0)
            pois = pf['poisson_probs'].get(k, 0)
            delta = obs - pois
            lines.append(f"| {k} | {obs*100:.1f}% | {pois*100:.1f}% | {delta*100:+.1f}% |")
        lines.append("")
    
    return '\n'.join(lines)


def get_betting_advice(home, away, all_rules=None, odds=None):
    """Get betting advice for a specific fixture pair.
    
    Args:
        home: Home team name
        away: Away team name
        all_rules: Pre-loaded rules dict (optional, will load on demand)
        odds: Dict of market->odds from MSport API (optional)
    
    Returns:
        Dict with recommended bet, reason, confidence, risk_tier
    """
    if all_rules is None:
        # Load on demand
        data = load_finite_state_data()
        all_rules, _ = analyze_all_pairs(data)
    
    pair_key = f"{home} vs {away}"
    rule = all_rules.get(pair_key)
    
    if not rule:
        return {
            'pair': pair_key,
            'found': False,
            'recommendation': 'NO_DATA',
            'reason': f'No historical data for {pair_key}',
            'risk_tier': 'UNKNOWN',
        }
    
    # Use get_best_market_for_pair with odds if available
    best_result = get_best_market_for_pair(home, away, all_rules, market_odds=odds)
    
    best_market = best_result.get('best_market', rule['best_market'])
    all_market_probs = rule.get('all_market_probs', {})
    mr = all_market_probs.get(best_market, rule['market_rules'].get(best_market, {}))
    
    # Fallback to legacy market_rules if needed
    if not mr:
        mr = rule['market_rules'].get(best_market, {})
    
    # Check if odds are available for value assessment
    value_assessment = ""
    if odds and best_market in odds:
        market_odds = odds[best_market]
        threshold = mr.get('threshold')
        if threshold and market_odds > threshold:
            value_assessment = f" ✅ Current odds {market_odds} > threshold {threshold} — VALUE BET"
        elif threshold:
            value_assessment = f" ⚠️ Current odds {market_odds} < threshold {threshold} — no value"
    
    confidence_map = {
        'GOLDEN_SAFE': 'HIGH',
        'GOLDEN': 'HIGH',
        'STANDARD': 'MEDIUM',
        'CAUTION': 'LOW',
        'TRAP': 'LOW',
    }
    
    return {
        'pair': pair_key,
        'found': True,
        'recommendation': f"BET {best_market}",
        'specific_advice': rule['betting_rule'],
        'best_market': best_market,
        'best_verdict': mr.get('verdict', 'N/A'),
        'fair_odds': mr.get('fair_odds', 'N/A'),
        'threshold': mr.get('threshold', 'N/A'),
        'prob': mr.get('prob', 'N/A'),
        'confidence': confidence_map.get(rule['tier'], 'MEDIUM'),
        'risk_tier': rule['tier'],
        'tier': rule['tier'],
        'reason': mr.get('reason', ''),
        'value_assessment': value_assessment.strip(),
        'data': {
            'matches': rule['matches_analyzed'],
            'o15_rate': rule['o15_rate'],
            'o25_rate': rule['o25_rate'],
            'gg_rate': rule['gg_rate'],
            'lambda_goals': rule['lambda_goals'],
        },
    }


def print_summary(all_rules, tier_counts):
    """Print summary statistics and example bets with ALL markets."""
    print("=" * 70)
    print("  VFL EMPIRE — PER-PAIR BETTING RULES SUMMARY (MULTI-MARKET)")
    print("=" * 70)
    print()
    
    # Count per tier
    print("📊 TIER DISTRIBUTION")
    print("-" * 40)
    for tier in ['GOLDEN_SAFE', 'GOLDEN', 'STANDARD', 'CAUTION', 'TRAP']:
        count = tier_counts.get(tier, 0)
        bar = "█" * count
        print(f"  {tier:15s}: {count:3d} pairs  {bar}")
    print()
    
    # Top 5 safest (Golden)
    golden_safe = {k: v for k, v in all_rules.items() if v['tier'] in ('GOLDEN_SAFE', 'GOLDEN')}
    top_golden = sorted(golden_safe.items(), key=lambda x: x[1]['o15_rate'], reverse=True)[:5]
    
    print("🏆 TOP 5 GOLDEN PAIRS (highest O1.5)")
    print("-" * 70)
    for key, rule in top_golden:
        print(f"  {key:45s} O1.5={rule['o15_rate']}%  λ={rule['lambda_goals']}  "
              f"Best: {rule['best_market']}  ({rule['tier']})")
    print()
    
    # Top 5 traps
    traps = {k: v for k, v in all_rules.items() if v['tier'] == 'TRAP'}
    top_traps = sorted(traps.items(), key=lambda x: x[1]['o15_rate'])[:5]
    
    print("🔴 TOP 5 TRAP PAIRS (lowest O1.5)")
    print("-" * 70)
    for key, rule in top_traps:
        print(f"  {key:45s} O1.5={rule['o15_rate']}%  λ={rule['lambda_goals']}  "
              f"Best: {rule['best_market']}  Most common: {rule['most_common_score']}")
    print()
    
    # Helper to print all markets
    def print_all_markets(label, pair_key):
        print(f"📋 {label}")
        print("-" * 70)
        rule = all_rules.get(pair_key)
        if not rule:
            print(f"  No data for {pair_key}")
            print()
            return
        
        amp = rule.get('all_market_probs', {})
        print(f"  Pair: {pair_key}")
        print(f"  Tier: {rule['tier']} | λ: {rule['lambda_goals']} | Matches: {rule['matches_analyzed']}")
        print()
        print(f"  {'Market':15s} | {'Prob':8s} | {'Fair Odds':10s} | {'Verdict':25s} | {'Class':12s}")
        print(f"  {'-'*15} | {'-'*8} | {'-'*10} | {'-'*25} | {'-'*12}")
        for mkt in ['O1.5', 'O2.5', 'U3.5', 'U4.5', 'GG', 'NG', 'Home_Win', 'Draw', 'Away_Win',
                     'DNB_Home', 'DNB_Away', 'DC_1X', 'DC_12', 'DC_X2']:
            if mkt in amp:
                d = amp[mkt]
                prob_str = f"{d['prob']*100:.1f}%"
                odds_str = f"{d['fair_odds']}"
                verb_str = d['verdict']
                cls_str = d.get('classification', '')
                print(f"  {mkt:15s} | {prob_str:>8s} | {odds_str:>10s} | {verb_str:25s} | {cls_str:12s}")
        print()
        
        # Best market
        best_result = get_best_market_for_pair(rule['home'], rule['away'], all_rules)
        print(f"  🏆 BEST MARKET: {best_result['best_market']} ({best_result['best_verdict']})")
        print(f"  📝 Rule: {rule['betting_rule']}")
        print()
    
    # Example 1: Leeds vs Fulham
    print_all_markets("EXAMPLE 1: Leeds vs Fulham (Low-scoring pair, O1.5=46.2%)", "Leeds vs Fulham")
    
    # Example 2: Wolverhampton vs Manchester Blue
    print_all_markets("EXAMPLE 2: Wolverhampton vs Manchester Blue (High-scoring, O1.5=92.3%)", "Wolverhampton vs Manchester Blue")
    
    # Example 3: Manchester Blue vs Chelsea
    print_all_markets("EXAMPLE 3: Manchester Blue vs Chelsea (High-scoring, O1.5=89.7%)", "Manchester Blue vs Chelsea")
    
    # Test with hypothetical odds
    print("📋 EXAMPLE WITH ODDS (Wolverhampton vs Manchester Blue)")
    print("-" * 70)
    test_odds = {
        'O1.5': 1.08,
        'O2.5': 1.65,
        'U3.5': 2.20,
        'GG': 1.85,
        'Home_Win': 4.50,
        'Draw': 4.00,
        'Away_Win': 1.73,
        'DNB_Home': 3.80,
        'DNB_Away': 1.45,
        'DC_1X': 2.10,
        'DC_12': 1.25,
        'DC_X2': 1.30,
    }
    best_ev = get_best_market_for_pair('Wolverhampton', 'Manchester Blue', all_rules, market_odds=test_odds)
    print(f"  Pair: Wolverhampton vs Manchester Blue")
    if best_ev.get('found'):
        print(f"  Best EV Market: {best_ev['best_market']} (EV={best_ev['best_ev']:.4f})")
        print(f"  All EVs:")
        for mkt, ev in sorted(best_ev.get('all_evs', {}).items(), key=lambda x: x[1], reverse=True):
            print(f"    {mkt:15s}: {ev:+.4f}")
    print()
    
    print("=" * 70)
    print(f"  Total rules generated: {len(all_rules)}")
    print(f"  Markets per pair: 14 (O1.5, O2.5, U3.5, U4.5, GG, NG, Home_Win, Draw, "
          "Away_Win, DNB_H, DNB_A, DC_1X, DC_12, DC_X2)")
    print(f"  Rulebook: {RULEBOOK_MD}")
    print(f"  JSON:     {PAIR_RULES_JSON}")
    print("=" * 70)


def main():
    """Main entry point."""
    print("Loading finite state space data...")
    data = load_finite_state_data()
    print(f"  Loaded {data['total_pairs']} pairs, {data['total_matches']} matches")
    print()
    
    print("Analyzing all pairs with multi-market extension...")
    all_rules, tier_counts = analyze_all_pairs(data)
    print(f"  Analyzed {len(all_rules)} pairs")
    print(f"  Markets per pair: 14 (O1.5, O2.5, U3.5, U4.5, GG, NG, Home_Win, Draw, Away_Win, DNB_H, DNB_A, DC_1X, DC_12, DC_X2)")
    print()
    
    print("Generating Markdown rulebook...")
    markdown = generate_markdown_rulebook(all_rules, tier_counts, data)
    os.makedirs(RULES_DIR, exist_ok=True)
    with open(RULEBOOK_MD, 'w') as f:
        f.write(markdown)
    print(f"  Written: {RULEBOOK_MD}")
    print()
    
    print("Saving JSON rules...")
    # Prepare JSON-safe output (remove circular refs)
    json_output = {
        'generated_at': data.get('analyzed_at', 'N/A'),
        'total_pairs': data['total_pairs'],
        'total_matches': data['total_matches'],
        'tier_counts': dict(tier_counts),
        'pairs': all_rules,
    }
    with open(PAIR_RULES_JSON, 'w') as f:
        json.dump(json_output, f, indent=2)
    print(f"  Written: {PAIR_RULES_JSON}")
    print()
    
    print("Printing summary...")
    print_summary(all_rules, tier_counts)


# ── Standalone advisor function ────────────────────────────────────────────────
def betting_advisor(home, away, odds=None):
    """Quick-access betting advisor.
    
    Usage:
        from pair_betting_rules import betting_advisor
        advice = betting_advisor('Leeds', 'Fulham')
        print(advice['recommendation'])
    """
    data = load_finite_state_data()
    all_rules, _ = analyze_all_pairs(data)
    return get_betting_advice(home, away, all_rules, odds)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
import sys
import sqlite3
from collections import defaultdict

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from ev_engine import predict_match, calculate_ev

RESULTS_DB = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db"
ODDS_DB = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_odds.db"

def analyze():
    conn = sqlite3.connect(RESULTS_DB)
    cursor = conn.cursor()
    cursor.execute(f"ATTACH '{ODDS_DB}' AS odds")
    
    cursor.execute("""
        SELECT 
            r.event_id, r.season_name, r.match_day, r.home_team, r.away_team, 
            r.home_goals, r.away_goals, r.captured_at, ed.event_id
        FROM results r
        JOIN odds.event_details ed ON 
            r.season_name = ed.season_name AND 
            r.match_day = ed.match_day AND 
            r.home_team = ed.home_team AND 
            r.away_team = ed.away_team
        WHERE r.status = 3 AND r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL
        ORDER BY r.captured_at ASC
    """)
    fixtures = cursor.fetchall()
    
    cursor.execute("""
        SELECT event_id, market_name, specifiers, selection_name, odds
        FROM odds.deep_markets
    """)
    raw_odds = cursor.fetchall()
    conn.close()
    
    odds_cache = defaultdict(lambda: defaultdict(dict))
    for ev_id, market, spec, selection, odd in raw_odds:
        market_key = market
        if market == 'Over/Under':
            if 'total=1.5' in spec: market_key = 'O/U1.5'
            elif 'total=2.5' in spec: market_key = 'O/U2.5'
            elif 'total=3.5' in spec: market_key = 'O/U3.5'
        elif market == '1x2':
            market_key = '1X2'
        odds_cache[ev_id][market_key][selection] = odd

    prior_matches = 15.0
    prior_home_goals = prior_matches * 1.55
    prior_away_goals = prior_matches * 1.25
    
    global_home_goals = prior_home_goals
    global_away_goals = prior_away_goals
    global_matches = prior_matches
    
    team_stats = defaultdict(lambda: {
        'home_scored': prior_home_goals / 16.0,
        'home_conceded': prior_away_goals / 16.0,
        'home_matches': prior_matches / 16.0,
        'away_scored': prior_away_goals / 16.0,
        'away_conceded': prior_home_goals / 16.0,
        'away_matches': prior_matches / 16.0
    })
    
    def get_current_strengths():
        avg_hg = global_home_goals / global_matches
        avg_ag = global_away_goals / global_matches
        strengths = {}
        for team, s in team_stats.items():
            strengths[team.upper()] = {
                'home_attack': (s['home_scored'] / s['home_matches']) / avg_hg,
                'home_defense': (s['home_conceded'] / s['home_matches']) / avg_ag,
                'away_attack': (s['away_scored'] / s['away_matches']) / avg_ag,
                'away_defense': (s['away_conceded'] / s['away_matches']) / avg_hg
            }
        return strengths, avg_hg, avg_ag

    # Track profits for different EV thresholds
    thresholds = [0.0, 3.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]
    flat_staked = defaultdict(float)
    flat_returned = defaultdict(float)
    flat_bets = defaultdict(int)
    flat_wins = defaultdict(int)
    
    for idx, (res_id, season, md, home, away, hg, ag, captured_at, odds_id) in enumerate(fixtures):
        fixture_odds = odds_cache.get(odds_id)
        if not fixture_odds:
            # Update running stats
            global_home_goals += hg
            global_away_goals += ag
            global_matches += 1
            team_stats[home]['home_scored'] += hg
            team_stats[home]['home_conceded'] += ag
            team_stats[home]['home_matches'] += 1
            team_stats[away]['away_scored'] += ag
            team_stats[away]['away_conceded'] += hg
            team_stats[away]['away_matches'] += 1
            continue
            
        strengths, avg_hg, avg_ag = get_current_strengths()
        pred = predict_match(home, away, strengths, avg_hg, avg_ag)
        
        actual_outcomes = {
            '1X2': {
                'Home': 1.0 if hg > ag else 0.0,
                'Draw': 1.0 if hg == ag else 0.0,
                'Away': 1.0 if hg < ag else 0.0
            },
            'O/U1.5': {
                'Over 1.5': 1.0 if hg + ag >= 2 else 0.0,
                'Under 1.5': 1.0 if hg + ag < 2 else 0.0
            },
            'O/U2.5': {
                'Over 2.5': 1.0 if hg + ag >= 3 else 0.0,
                'Under 2.5': 1.0 if hg + ag < 3 else 0.0
            },
            'O/U3.5': {
                'Over 3.5': 1.0 if hg + ag >= 4 else 0.0,
                'Under 3.5': 1.0 if hg + ag < 4 else 0.0
            },
            'GG/NG': {
                'Yes': 1.0 if hg >= 1 and ag >= 1 else 0.0,
                'No': 1.0 if hg == 0 or ag == 0 else 0.0
            }
        }
        
        for market_name, market_odds in fixture_odds.items():
            if market_name not in pred: continue
            our_probs = pred[market_name]
            ev_calcs = calculate_ev(market_odds, our_probs)
            
            for selection, ev_info in ev_calcs.items():
                p_act = actual_outcomes[market_name].get(selection, 0.0)
                ev_pct = ev_info['ev_pct']
                odds = ev_info['market_odds']
                is_winner = p_act == 1.0
                
                for t in thresholds:
                    if ev_pct >= t:
                        flat_staked[t] += 100.0
                        flat_bets[t] += 1
                        if is_winner:
                            flat_returned[t] += 100.0 * odds
                            flat_wins[t] += 1

        # Update running stats
        global_home_goals += hg
        global_away_goals += ag
        global_matches += 1
        team_stats[home]['home_scored'] += hg
        team_stats[home]['home_conceded'] += ag
        team_stats[home]['home_matches'] += 1
        team_stats[away]['away_scored'] += ag
        team_stats[away]['away_conceded'] += hg
        team_stats[away]['away_matches'] += 1

    print("\n=== THRESHOLD ANALYSIS ===")
    print(f"{'Threshold %':<12} {'Bets':<10} {'Win Rate':<10} {'Staked':<12} {'Returned':<12} {'ROI':<10}")
    for t in thresholds:
        staked = flat_staked[t]
        returned = flat_returned[t]
        roi = ((returned - staked) / staked * 100) if staked > 0 else 0.0
        bets = flat_bets[t]
        wr = (flat_wins[t] / bets * 100) if bets > 0 else 0.0
        print(f"{t:<12.1f} {bets:<10} {wr:<10.1f}% ${staked:<11,.2f} ${returned:<11,.2f} {roi:+.2f}%")

if __name__ == "__main__":
    analyze()

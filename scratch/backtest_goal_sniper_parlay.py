import pandas as pd
import numpy as np
import sqlite3
import json

def run_goal_parlay_backtest():
    print("🚀 Initializing Goal Sniper Parlay Backtest (Out-Of-Sample)...")
    DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
    
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT season, day, home, away, h, a, total, gg, o25, o_o25, o_u25 
    FROM matches 
    WHERE season IS NOT NULL AND total IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    df.drop_duplicates(subset=['season', 'day', 'home', 'away'], inplace=True)
    conn.close()

    df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
    df['season_num'] = df['season_num'].fillna(df['season_num'].max())

    # Calculate Standings (Lag 1)
    home_results = df[['season', 'season_num', 'day', 'home', 'h', 'a']].copy()
    home_results.rename(columns={'home': 'team', 'h': 'gf', 'a': 'ga'}, inplace=True)
    home_results['pts'] = np.where(home_results['gf'] > home_results['ga'], 3, np.where(home_results['gf'] == home_results['ga'], 1, 0))

    away_results = df[['season', 'season_num', 'day', 'away', 'a', 'h']].copy()
    away_results.rename(columns={'away': 'team', 'a': 'gf', 'h': 'ga'}, inplace=True)
    away_results['pts'] = np.where(away_results['gf'] > away_results['ga'], 3, np.where(away_results['gf'] == away_results['ga'], 1, 0))

    df_teams = pd.concat([home_results, away_results], ignore_index=True)
    df_teams.sort_values(['season', 'day'], inplace=True)
    df_teams['gd'] = df_teams['gf'] - df_teams['ga']

    df_teams['cum_pts'] = df_teams.groupby(['season', 'team'])['pts'].cumsum()
    df_teams['cum_gd'] = df_teams.groupby(['season', 'team'])['gd'].cumsum()
    df_teams['cum_gf'] = df_teams.groupby(['season', 'team'])['gf'].cumsum()

    df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(1).fillna(0)
    df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(1).fillna(0)
    df_teams['prev_gf'] = df_teams.groupby(['season', 'team'])['cum_gf'].shift(1).fillna(0)

    df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd', 'prev_gf'], ascending=[True, True, False, False, False], inplace=True)
    df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
    df_teams['lag_tier'] = pd.cut(df_teams['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])

    home_ranks = df_teams[['season', 'day', 'team', 'lag_tier', 'rank']].rename(columns={'team': 'home', 'lag_tier': 'home_tier', 'rank': 'home_rank'})
    away_ranks = df_teams[['season', 'day', 'team', 'lag_tier', 'rank']].rename(columns={'team': 'away', 'lag_tier': 'away_tier', 'rank': 'away_rank'})

    df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
    df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')
    
    # Split Data (Last 15 Seasons Out of Sample)
    all_seasons = sorted(df['season_num'].dropna().unique())
    test_seasons = all_seasons[-15:]
    
    df_train = df[~df['season_num'].isin(test_seasons)].copy()
    df_test = df[df['season_num'].isin(test_seasons)].sort_values(by=['season_num', 'day'])
    print(f"📚 Testing on last 15 seasons...")

    # Load the pillars from the file we generated
    PILLARS_PATH = '/home/ubuntu/faith-workspace/vfl-empire/data/goal_pillars.json'
    with open(PILLARS_PATH, 'r') as f:
        pillars_list = json.load(f)
        
    elite_pillars = {}
    for p in pillars_list:
        if p['confidence'] == '100%' and p['occurrences'] >= 100:
            key = (p['home'], p['away'], p['home_tier'], p['away_tier'])
            elite_pillars[key] = p['market']

    print(f"💎 Loaded {len(elite_pillars)} ELITE Goal Pillars from model.")

    # 2. Backtest via Parlay (Grouping by Season & Matchday)
    parlays_placed = 0
    parlays_won = 0
    parlays_lost = 0
    total_legs = 0
    total_legs_won = 0
    
    bankroll_flat = 100.0  # Starts with 100
    bankroll_compound = 100.0 # Full reinvestment
    
    # 6-Cycle Compounding vars
    base_stake = 100.0
    cycle_stake = base_stake
    cycle_wins = 0
    total_banked_profit = 0.0
    completed_cycles = 0
    
    print("\n===================================================================================================")
    print(" 🎯 ELITE GOAL SNIPER PARLAY: FINANCIAL SIMULATION (15 SEASONS)")
    print("===================================================================================================")
    
    for (season, day), md_group in df_test.groupby(['season_num', 'day']):
        legs = []
        parlay_status = True
        parlay_odds = 1.0
        
        for _, row in md_group.iterrows():
            key = (str(row['home']), str(row['away']), str(row['home_tier']), str(row['away_tier']))
            if key in elite_pillars:
                market = elite_pillars[key]
                total = row['total']
                
                # Assign Odds
                leg_odds = 1.0
                if market == "Under 2.5" and not pd.isna(row['o_u25']) and row['o_u25'] > 1.0: leg_odds = row['o_u25']
                elif market == "Over 2.5" and not pd.isna(row['o_o25']) and row['o_o25'] > 1.0: leg_odds = row['o_o25']
                elif market == "Under 3.5": leg_odds = 1.15 # Conservative heuristic
                elif market == "Over 1.5": leg_odds = 1.20 # Conservative heuristic
                else: leg_odds = 1.10 # Fallback
                
                parlay_odds *= leg_odds
                
                # Check if leg won
                leg_won = False
                if market == "Under 3.5" and total < 3.5: leg_won = True
                elif market == "Over 1.5" and total > 1.5: leg_won = True
                elif market == "Under 2.5" and total < 2.5: leg_won = True
                elif market == "Over 2.5" and total > 2.5: leg_won = True
                
                legs.append(f"{row['home']} v {row['away']} ({market} @ {leg_odds:.2f} | Result: {int(total)} -> {'✅' if leg_won else '❌'})")
                
                total_legs += 1
                if leg_won: total_legs_won += 1
                else: parlay_status = False
                
        if len(legs) > 0:
            parlays_placed += 1
            if parlay_status: 
                parlays_won += 1
                profit_flat = 100.0 * (parlay_odds - 1)
                bankroll_flat += profit_flat
                bankroll_compound *= parlay_odds
                
                # 6-Cycle Logic
                cycle_stake *= parlay_odds
                cycle_wins += 1
                if cycle_wins == 6:
                    completed_cycles += 1
                    cycle_profit = cycle_stake - base_stake
                    total_banked_profit += cycle_profit
                    cycle_wins = 0
                    cycle_stake = base_stake
            else: 
                parlays_lost += 1
                bankroll_flat -= 100.0
                bankroll_compound = 0.0 # Busted
                
                # 6-Cycle Logic
                cycle_wins = 0
                cycle_stake = base_stake
            
            status_str = f"🏆 WON (+₦{100*(parlay_odds-1):.2f})" if parlay_status else "💀 LOST (-₦100)"
            print(f"Season {int(season)} | MD {int(day)} | {len(legs)}-Leg Parlay @ {parlay_odds:.2f} | {status_str}")
            print(f"   => CYCLE STATUS: Step {cycle_wins}/6 | Current Cycle Stake: ₦{cycle_stake:,.2f}")

    print("\n===================================================================================================")
    print(" 🏁 FINAL FINANCIAL RESULTS (Starting Capital: ₦100)")
    print("===================================================================================================")
    print(f"Total Parlays Placed:  {parlays_placed}")
    print(f"Parlays Won:           {parlays_won}")
    print(f"Parlays Lost:          {parlays_lost}")
    if parlays_placed > 0:
        print(f"Parlay Hit Rate:       {(parlays_won/parlays_placed)*100:.2f}%")
        
    print(f"\nFLAT BETTING (₦100 per bet):")
    print(f"Final Bankroll:        ₦{bankroll_flat:,.2f}")
    
    print(f"\n6-CYCLE COMPOUNDING (Reset to ₦100 after 6 wins):")
    print(f"Completed Cycles:      {completed_cycles}")
    print(f"Total Banked Profit:   ₦{total_banked_profit:,.2f}")
    # Add ongoing cycle value
    ongoing_value = cycle_stake - base_stake
    print(f"Ongoing Cycle Value:   ₦{ongoing_value:,.2f} (Step {cycle_wins}/6)")
    print(f"Total Portfolio:       ₦{total_banked_profit + ongoing_value + base_stake:,.2f}")

if __name__ == '__main__':
    run_goal_parlay_backtest()

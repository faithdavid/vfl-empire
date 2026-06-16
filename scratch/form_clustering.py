import pandas as pd
import sys
from collections import defaultdict

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def calculate_form_points(df):
    df = df.sort_values(by=['season_num', 'day'])
    history = defaultdict(lambda: defaultdict(list))
    
    home_form_list = []
    away_form_list = []
    
    for _, row in df.iterrows():
        season = row['season_num']
        home = row['home']
        away = row['away']
        h_goals = row['h']
        a_goals = row['a']
        
        # Calculate points for last 5 matches
        h_pts = sum(history[season][home][-5:]) if len(history[season][home]) >= 5 else -1
        a_pts = sum(history[season][away][-5:]) if len(history[season][away]) >= 5 else -1
        
        def categorize(pts):
            if pts == -1: return 'N/A'
            if pts >= 10: return 'HOT'  # 10+ points in 5 games
            if pts >= 5: return 'AVG'   # 5-9 points
            return 'COLD'               # 0-4 points
            
        home_form_list.append(categorize(h_pts))
        away_form_list.append(categorize(a_pts))
        
        if h_goals > a_goals:
            history[season][home].append(3)
            history[season][away].append(0)
        elif h_goals == a_goals:
            history[season][home].append(1)
            history[season][away].append(1)
        else:
            history[season][home].append(0)
            history[season][away].append(3)
            
    df['home_form'] = home_form_list
    df['away_form'] = away_form_list
    return df

def analyze_form_clusters(df):
    df = df[(df['home_form'] != 'N/A') & (df['away_form'] != 'N/A')]
    
    # DROP EXACT FIXTURES! Only cluster by Tier + Form
    grouped = df.groupby(['home_tier', 'away_tier', 'home_form', 'away_form'])
    
    results = []
    
    for name, group in grouped:
        h_tier, a_tier, h_form, a_form = name
        matches = len(group)
        
        if matches < 50: # Require 50 occurrences for statistically significant form analysis!
            continue
            
        hw = sum(group['h'] > group['a']) / matches
        dr = sum(group['h'] == group['a']) / matches
        aw = sum(group['h'] < group['a']) / matches
        
        results.append({
            'tiers': f"{h_tier} vs {a_tier}",
            'form': f"{h_form} vs {a_form}",
            'matches': matches,
            'hw': hw * 100,
            'dr': dr * 100,
            'aw': aw * 100
        })
        
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        df_results = df_results.sort_values(by=['hw'], ascending=False)
    return df_results

def main():
    print("Loading historical data...")
    df, _ = extract_panel_data_with_standings()
    
    # Use 100 seasons
    all_seasons = sorted(df['season_num'].dropna().unique())
    target_seasons = all_seasons[-100:]
    df_100 = df[df['season_num'].isin(target_seasons)].copy()
    
    df_100 = calculate_form_points(df_100)
    cluster_df = analyze_form_clusters(df_100)
    
    print("\n=====================================================================================")
    print(" 🔮 FORM + TIER CLUSTERING (TEAMS ABSTRACTED)")
    print("=====================================================================================")
    
    if cluster_df.empty:
        print("No clusters found with >= 50 occurrences.")
        return
        
    print(f"{'TIERS':<15} | {'5-DAY FORM (H v A)':<20} | {'FREQ':<6} | {'HW%':<5} | {'DR%':<5} | {'AW%':<5}")
    print("-" * 75)
    
    # Top 15 Home Win Probabilities
    for _, row in cluster_df.head(15).iterrows():
        print(f"{row['tiers']:<15} | {row['form']:<20} | {row['matches']:<6} | {row['hw']:<5.1f} | {row['dr']:<5.1f} | {row['aw']:<5.1f}")
        
    print("\n[...]\n")
    
    # Top 15 Away Win Probabilities
    cluster_aw = cluster_df.sort_values(by=['aw'], ascending=False)
    for _, row in cluster_aw.head(15).iterrows():
        print(f"{row['tiers']:<15} | {row['form']:<20} | {row['matches']:<6} | {row['hw']:<5.1f} | {row['dr']:<5.1f} | {row['aw']:<5.1f}")

if __name__ == '__main__':
    main()

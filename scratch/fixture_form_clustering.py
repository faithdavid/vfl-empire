import pandas as pd
import sys
from collections import defaultdict
import json

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def calculate_form_history(df):
    """
    Adds rolling 5-match form history for both Home and Away teams.
    Form is represented as a string like 'WWDDL'.
    """
    df = df.sort_values(by=['season_num', 'day'])
    
    # Store history per season per team
    # Format: {season_num: {team_name: ['W', 'D', 'L', ...]}}
    history = defaultdict(lambda: defaultdict(list))
    
    home_form_list = []
    away_form_list = []
    
    for _, row in df.iterrows():
        season = row['season_num']
        day = row['day']
        home = row['home']
        away = row['away']
        h_goals = row['h']
        a_goals = row['a']
        
        # Get current form (last 5 matches) before this match is played
        home_form = "".join(history[season][home][-5:]) if len(history[season][home]) > 0 else "NONE"
        away_form = "".join(history[season][away][-5:]) if len(history[season][away]) > 0 else "NONE"
        
        home_form_list.append(home_form)
        away_form_list.append(away_form)
        
        # Determine match result
        if h_goals > a_goals:
            h_res, a_res = 'W', 'L'
        elif h_goals == a_goals:
            h_res, a_res = 'D', 'D'
        else:
            h_res, a_res = 'L', 'W'
            
        # Update history
        history[season][home].append(h_res)
        history[season][away].append(a_res)
        
    df['home_form'] = home_form_list
    df['away_form'] = away_form_list
    return df

def analyze_clusters(df):
    # Filter out matches where teams don't have 5 games of history yet
    df = df[(df['home_form'].str.len() == 5) & (df['away_form'].str.len() == 5)]
    
    # Define match outcome
    df['outcome'] = df.apply(lambda row: 'HW' if row['h'] > row['a'] else ('D' if row['h'] == row['a'] else 'AW'), axis=1)
    
    # Group by Fixture + Tier + Outcome
    grouped = df.groupby(['home', 'away', 'home_tier', 'away_tier', 'outcome'])
    
    results = []
    
    for name, group in grouped:
        home, away, h_tier, a_tier, outcome = name
        occurrences = len(group)
        
        # Find the most common form sequence that preceded this exact outcome
        top_home_form = group['home_form'].value_counts().index[0] if not group['home_form'].empty else "N/A"
        top_away_form = group['away_form'].value_counts().index[0] if not group['away_form'].empty else "N/A"
        
        results.append({
            'fixture': f"{home} vs {away}",
            'tiers': f"{h_tier} vs {a_tier}",
            'outcome': outcome,
            'occurrences': occurrences,
            'common_home_form_prior': top_home_form,
            'common_away_form_prior': top_away_form
        })
        
    return pd.DataFrame(results)

def main():
    print("Loading historical data...")
    df, _ = extract_panel_data_with_standings()
    
    # Filter to last 30 seasons
    all_seasons = sorted(df['season_num'].dropna().unique())
    target_seasons = all_seasons[-30:]
    df_30 = df[df['season_num'].isin(target_seasons)].copy()
    
    print(f"Calculating form history for 30 seasons ({len(df_30)} matches)...")
    df_30 = calculate_form_history(df_30)
    
    print("Clustering outcomes by Form...")
    cluster_df = analyze_clusters(df_30)
    
    # Filter for interesting insights: Outcomes that happened at least 5 times in these 30 seasons
    significant_clusters = cluster_df[cluster_df['occurrences'] >= 5].sort_values(by=['fixture', 'tiers', 'outcome'])
    
    # Print a sample of the clusters
    print("\n=========================================================================================")
    print(" 🔍 FORM-BASED CLUSTERING: WHAT HAPPENED 5 DAYS PRIOR TO SPECIFIC OUTCOMES?")
    print("=========================================================================================")
    print(f"{'FIXTURE':<25} | {'TIERS':<10} | {'OUTCOME':<7} | {'FREQ':<4} | {'PRIOR HOME FORM':<15} | {'PRIOR AWAY FORM'}")
    print("-" * 89)
    
    for _, row in significant_clusters.head(30).iterrows():
        print(f"{row['fixture']:<25} | {row['tiers']:<10} | {row['outcome']:<7} | {row['occurrences']:<4} | {row['common_home_form_prior']:<15} | {row['common_away_form_prior']}")

if __name__ == '__main__':
    main()

import pandas as pd
import sys
import numpy as np

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def analyze_season_quotas(df):
    """
    Calculates the final end-of-season (Matchday 30) W/D/L totals for every team
    across all historical seasons, and groups them by their final Macro Tier.
    """
    # Filter to only the final matchday of each season (assuming 30 matchdays per season)
    # Wait, some seasons might be 38. Let's find the max matchday per season.
    max_days = df.groupby('season_num')['day'].max().reset_index()
    # Only keep seasons that reached their completion (e.g. >= 30)
    valid_seasons = max_days[max_days['day'] >= 30]['season_num']
    
    df = df[df['season_num'].isin(valid_seasons)]
    
    # Calculate running W/D/L for every team per season
    # To do this efficiently, we can just aggregate all results per team per season
    
    records = []
    grouped = df.groupby(['season_num'])
    
    for season, group in grouped:
        team_stats = {team: {'W': 0, 'D': 0, 'L': 0, 'Pts': 0, 'Tier': None} for team in pd.concat([group['home'], group['away']]).unique()}
        
        for _, row in group.iterrows():
            h, a = row['home'], row['away']
            hg, ag = row['h'], row['a']
            
            if hg > ag:
                team_stats[h]['W'] += 1
                team_stats[h]['Pts'] += 3
                team_stats[a]['L'] += 1
            elif hg == ag:
                team_stats[h]['D'] += 1
                team_stats[h]['Pts'] += 1
                team_stats[a]['D'] += 1
                team_stats[a]['Pts'] += 1
            else:
                team_stats[h]['L'] += 1
                team_stats[a]['W'] += 1
                team_stats[a]['Pts'] += 3
                
            # If this is the final matchday, record their tier
            # We can approximate final tier by sorting Pts at the end
            
        # Assign final tiers based on Pts at the end of the season
        sorted_teams = sorted(team_stats.items(), key=lambda x: x[1]['Pts'], reverse=True)
        total_teams = len(sorted_teams)
        
        for i, (team, stats) in enumerate(sorted_teams):
            rank = i + 1
            if rank <= total_teams * 0.25: tier = 'T1'
            elif rank <= total_teams * 0.50: tier = 'T2'
            elif rank <= total_teams * 0.75: tier = 'T3'
            else: tier = 'T4'
            
            records.append({
                'season': season,
                'team': team,
                'tier': tier,
                'W': stats['W'],
                'D': stats['D'],
                'L': stats['L'],
                'Pts': stats['Pts']
            })
            
    df_records = pd.DataFrame(records)
    
    print("\n=========================================================================")
    print(" 🏆 END-OF-SEASON QUOTA ANALYSIS (W/D/L LIMITS PER TIER)")
    print("=========================================================================")
    
    for tier in ['T1', 'T2', 'T3', 'T4']:
        tier_data = df_records[df_records['tier'] == tier]
        
        w_min, w_mean, w_max = tier_data['W'].min(), tier_data['W'].mean(), tier_data['W'].max()
        d_min, d_mean, d_max = tier_data['D'].min(), tier_data['D'].mean(), tier_data['D'].max()
        l_min, l_mean, l_max = tier_data['L'].min(), tier_data['L'].mean(), tier_data['L'].max()
        pts_min, pts_mean, pts_max = tier_data['Pts'].min(), tier_data['Pts'].mean(), tier_data['Pts'].max()
        
        # Calculate percentiles to find the "hard caps"
        w_95 = np.percentile(tier_data['W'], 95)
        w_05 = np.percentile(tier_data['W'], 5)
        
        print(f"\n[{tier}] QUOTAS (Based on {len(tier_data)} team seasons):")
        print(f"  WINS:   Mean: {w_mean:.1f}  | Strict Range (5th-95th %): {w_05:.0f} to {w_95:.0f}  | Absolute Max: {w_max}")
        print(f"  DRAWS:  Mean: {d_mean:.1f}  | Absolute Range: {d_min} to {d_max}")
        print(f"  LOSSES: Mean: {l_mean:.1f}  | Absolute Range: {l_min} to {l_max}")
        print(f"  POINTS: Mean: {pts_mean:.1f}  | Absolute Range: {pts_min} to {pts_max}")

def main():
    print("Loading historical data...")
    df, _ = extract_panel_data_with_standings()
    analyze_season_quotas(df)

if __name__ == '__main__':
    main()

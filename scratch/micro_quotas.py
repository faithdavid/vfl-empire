import pandas as pd
import sys
import numpy as np

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def analyze_micro_season_quotas(df):
    """
    Calculates final end-of-season W/D/L totals for every team
    and groups them by their final MICRO Tier (T1A, T1B, etc.).
    """
    max_days = df.groupby('season_num')['day'].max().reset_index()
    valid_seasons = max_days[max_days['day'] >= 30]['season_num']
    
    df = df[df['season_num'].isin(valid_seasons)]
    
    records = []
    grouped = df.groupby(['season_num'])
    
    for season, group in grouped:
        team_stats = {team: {'W': 0, 'D': 0, 'L': 0, 'Pts': 0} for team in pd.concat([group['home'], group['away']]).unique()}
        
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
                
        sorted_teams = sorted(team_stats.items(), key=lambda x: x[1]['Pts'], reverse=True)
        total_teams = len(sorted_teams)
        
        # In a 16 team league, pairs map to micro tiers
        for i, (team, stats) in enumerate(sorted_teams):
            rank = i + 1
            
            if rank <= 2: micro_tier = 'T1A'      # 1-2
            elif rank <= 4: micro_tier = 'T1B'    # 3-4
            elif rank <= 6: micro_tier = 'T2A'    # 5-6
            elif rank <= 8: micro_tier = 'T2B'    # 7-8
            elif rank <= 10: micro_tier = 'T3A'   # 9-10
            elif rank <= 12: micro_tier = 'T3B'   # 11-12
            elif rank <= 14: micro_tier = 'T4A'   # 13-14
            else: micro_tier = 'T4B'              # 15-16
            
            records.append({
                'season': season,
                'team': team,
                'micro_tier': micro_tier,
                'W': stats['W'],
                'D': stats['D'],
                'L': stats['L'],
                'Pts': stats['Pts']
            })
            
    df_records = pd.DataFrame(records)
    
    print("\n=========================================================================")
    print(" 🔬 MICRO TIER QUOTAS: THE ABSOLUTE ENGINE LIMITS")
    print("=========================================================================")
    
    micro_tiers = ['T1A', 'T1B', 'T2A', 'T2B', 'T3A', 'T3B', 'T4A', 'T4B']
    
    for mt in micro_tiers:
        tier_data = df_records[df_records['micro_tier'] == mt]
        
        w_min, w_mean, w_max = tier_data['W'].min(), tier_data['W'].mean(), tier_data['W'].max()
        d_mean = tier_data['D'].mean()
        l_mean = tier_data['L'].mean()
        
        # Calculate strict range (10th to 90th percentile to get the hardcore reliable core)
        w_90 = np.percentile(tier_data['W'], 90)
        w_10 = np.percentile(tier_data['W'], 10)
        
        print(f"\n[{mt}] QUOTAS (Positions for this tier):")
        print(f"  🏆 WINS:   Average: {w_mean:.1f} | Core Quota (10-90%): {w_10:.0f} to {w_90:.0f} | Cap (Max): {w_max}")
        print(f"  🤝 DRAWS:  Average: {d_mean:.1f}")
        print(f"  💔 LOSSES: Average: {l_mean:.1f}")

def main():
    print("Loading historical data...")
    df, _ = extract_panel_data_with_standings()
    analyze_micro_season_quotas(df)

if __name__ == '__main__':
    main()

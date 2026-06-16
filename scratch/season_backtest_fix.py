import sqlite3
import pandas as pd

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, oh, od, oa, h, a, outcome FROM matches WHERE oh IS NOT NULL ORDER BY season, day", conn_hist)

# Find seasons with the most odds data
season_counts = df_all['season'].value_counts()
top_seasons = season_counts[season_counts >= 200].index.tolist()

if len(top_seasons) < 2:
    print("Not enough seasons with odds data found.")
    exit()

last_season = top_seasons[0]
prev_season = top_seasons[1]

def run_backtest(season_id):
    df_season = df_all[df_all['season'] == season_id].copy()
    if df_season.empty: return
    
    total_matches = 0
    correct_predictions = 0
    bankroll = 0.0 # Starting at 0, betting 1 unit per match
    
    md_stats = []
    
    for day in df_season['day'].unique():
        day_matches = df_season[df_season['day'] == day]
        if day_matches.empty: continue
        
        day_correct = 0
        day_profit = 0.0
        
        for _, row in day_matches.iterrows():
            oh, od, oa = row['oh'], row['od'], row['oa']
            
            # Predict the favorite (lowest odds)
            pred = 'HOME'
            pred_odds = oh
            if oa < oh and oa < od:
                pred = 'AWAY'
                pred_odds = oa
            elif od < oh and od < oa:
                pred = 'DRAW'
                pred_odds = od
                
            actual = row['outcome']
            total_matches += 1
            
            if pred == actual:
                correct_predictions += 1
                profit = pred_odds - 1.0
            else:
                profit = -1.0
                
            bankroll += profit
            day_correct += (1 if pred == actual else 0)
            day_profit += profit
            
        md_stats.append({
            'Matchday': day,
            'Accuracy': f"{(day_correct / len(day_matches)) * 100:.1f}%",
            'Profit': day_profit
        })
        
    acc = correct_predictions / total_matches if total_matches > 0 else 0
    
    print(f"\n=============================================")
    print(f"BACKTEST RESULTS: SEASON {season_id}")
    print(f"=============================================")
    print(f"Strategy: Bet 1 Unit on Pre-Match Favorite for EVERY Fixture.")
    print(f"Total Matches Bet: {total_matches}")
    print(f"Total Correct: {correct_predictions}")
    print(f"Overall Accuracy: {acc*100:.1f}%")
    print(f"Total Profit/Loss: {bankroll:+.2f} Units")
    
    print("\nTop 5 Most Profitable Matchdays:")
    df_md = pd.DataFrame(md_stats).sort_values(by='Profit', ascending=False)
    print(df_md.head(5).to_string(index=False))
    
    print("\nBottom 5 Worst Matchdays:")
    print(df_md.tail(5).to_string(index=False))

print("Executing Full-Season Backtests using Bookmaker Odds...")
run_backtest(last_season)
run_backtest(prev_season)


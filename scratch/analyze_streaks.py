import sqlite3
import pandas as pd
from collections import defaultdict

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db"

def analyze_streaks():
    conn = sqlite3.connect(DB_PATH)
    # Order by season_id and match_day
    query = """
    SELECT season_id, match_day, home_team, away_team, home_goals, away_goals 
    FROM results 
    ORDER BY season_id, match_day
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    teams = pd.concat([df['home_team'], df['away_team']]).unique()
    team_streaks = {team: [] for team in teams}
    current_streaks = {team: 0 for team in teams}

    for _, row in df.iterrows():
        h = row['home_team']
        a = row['away_team']
        hg = row['home_goals']
        ag = row['away_goals']

        # Home team result
        if hg > ag:
            current_streaks[h] += 1
        else:
            if current_streaks[h] > 0:
                team_streaks[h].append(current_streaks[h])
            current_streaks[h] = 0

        # Away team result
        if ag > hg:
            current_streaks[a] += 1
        else:
            if current_streaks[a] > 0:
                team_streaks[a].append(current_streaks[a])
            current_streaks[a] = 0

    print("--- Max Win Streaks by Team ---")
    results = []
    for team, streaks in team_streaks.items():
        if streaks:
            max_s = max(streaks)
            avg_s = sum(streaks) / len(streaks)
            results.append({'team': team, 'max_streak': max_s, 'avg_streak': round(avg_s, 2), 'count': len(streaks)})
    
    res_df = pd.DataFrame(results).sort_values(by='max_streak', ascending=False)
    print(res_df.to_string(index=False))

    # Also check how many streaks are >= 5
    print("\n--- Streaks of 5 or more ---")
    long_streaks = []
    for team, streaks in team_streaks.items():
        ls = [s for s in streaks if s >= 5]
        if ls:
            long_streaks.append({'team': team, 'streaks_ge_5': len(ls)})
    
    ls_df = pd.DataFrame(long_streaks).sort_values(by='streaks_ge_5', ascending=False)
    print(ls_df.to_string(index=False))

if __name__ == "__main__":
    analyze_streaks()

import pandas as pd
import subprocess

def get_sql_output(query):
    cmd = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-F", ",", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()

def analyze_db_odds():
    # Join vfl_odds_v2 with vfl_results_v2 using teams and matchday
    query = """
    SELECT 
        o.u25, o.o15, o.o25, r.home_goals, r.away_goals
    FROM vfl_odds_v2 o
    JOIN vfl_seasons s ON o.season_id = s.season_name
    JOIN vfl_matchdays m ON s.id = m.season_id AND o.matchday_number = m.matchday_number
    JOIN vfl_results_v2 r ON m.id = r.matchday_id AND o.home_team = r.home_team AND o.away_team = r.away_team
    """
    csv_data = get_sql_output(query)
    if not csv_data:
        print("No data found in DB with team/md join.")
        return

    # Write to temp file
    with open('/tmp/odds_results.csv', 'w') as f:
        f.write("u25,o15,o25,hg,ag\n")
        f.write(csv_data)
    
    df = pd.read_csv('/tmp/odds_results.csv')
    df['total_goals'] = df['hg'] + df['ag']
    df['is_u25'] = df['total_goals'] < 2.5
    df['is_o15'] = df['total_goals'] > 1.5
    
    # Analyze
    print("=== Under 2.5 Locks (Success Rate > 90%, Count > 10) ===")
    u25_locks = df.groupby('u25')['is_u25'].agg(['mean', 'count'])
    u25_locks = u25_locks[(u25_locks['count'] >= 10) & (u25_locks['mean'] > 0.9)]
    print(u25_locks.sort_values('mean', ascending=False))
    
    print("\n=== Over 1.5 Locks (Success Rate > 90%, Count > 10) ===")
    o15_locks = df.groupby('o15')['is_o15'].agg(['mean', 'count'])
    o15_locks = o15_locks[(o15_locks['count'] >= 10) & (o15_locks['mean'] > 0.9)]
    print(o15_locks.sort_values('mean', ascending=False))

if __name__ == "__main__":
    analyze_db_odds()

### 🏆 LIVE LEAGUE TABLE FORMAT

This format is to be used for all future outputs of the live league table. It MUST include Points, Wins, Draws, Losses, Goals For, Goals Against, Goal Differential, and the exact Form string.

**Columns Required:**
1. **Rank:** Current position.
2. **Team:** Team name.
3. **Points (pts):** Total league points (3 for W, 1 for D, 0 for L).
4. **W:** Total Wins.
5. **D:** Total Draws.
6. **L:** Total Losses.
7. **GF:** Goals For (Goals Scored).
8. **GA:** Goals Against (Goals Conceded).
9. **GD:** Goal Differential (GF - GA).
10. **Form:** The last 5 results (Oldest -> Newest).

**Example Output:**

| Rank | Team | Points | W | D | L | GF | GA | GD | Form |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Manchester Blue** | **29** | 9 | 2 | 1 | 27 | 8 | +19 | WDWWW |
| **16** | **Bournemouth** | **5** | 0 | 5 | 7 | 7 | 22 | -15 | DLDLL |

**Query Script Location:**
`/home/ubuntu/faith-workspace/vfl-empire/scratch/get_pg_standings.py` is currently configured to generate data matching this exact schema from the `vfl_league_snapshots` Postgres table.

**CRITICAL RULE FOR PREDICTIONS:**
The league table must **always** be updated to Matchday `X - 1` before attempting to make predictions for Matchday `X`. 
For example, when predicting Matchday 14, the Postgres query MUST use `WHERE played = 13`.

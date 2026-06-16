import json
import subprocess
import msport_api
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DISCORD_TARGET = "discord:1507922324072960031:1512659823081164891"
PATTERNS_FILE = "/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json"
MICRO_PATTERNS_FILE = "/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json"

def get_tier(rank: int) -> str:
    if rank <= 4:
        return "T1"
    elif rank <= 8:
        return "T2"
    elif rank <= 12:
        return "T3"
    else:
        return "T4"

def get_micro_tier(rank: int) -> str:
    if rank <= 2: return "A"
    elif rank <= 4: return "B"
    elif rank <= 6: return "C"
    elif rank <= 8: return "D"
    elif rank <= 10: return "E"
    elif rank <= 12: return "F"
    elif rank <= 14: return "G"
    else: return "H"

def infer_exact_score(row: dict) -> str:
    """Infers exact scores based on intersecting high-confidence (>85%) or low-confidence (<15%) market locks."""
    u15 = row.get('w_u15_rate', 0) >= 0.85
    u25 = row.get('w_u25_rate', 0) >= 0.85
    u35 = row.get('w_u35_rate', 0) >= 0.85
    o15 = row.get('w_o15_rate', 0) >= 0.85
    o25 = row.get('w_o25_rate', 0) >= 0.85
    o35 = row.get('w_o35_rate', 0) >= 0.85
    gg = row.get('w_gg_rate', 0) >= 0.85
    ng = row.get('w_gg_rate', 1) <= 0.15
    hw = row.get('w_1_rate', 0) >= 0.85
    dr = row.get('w_x_rate', 0) >= 0.85
    aw = row.get('w_2_rate', 0) >= 0.85
    
    if dr and u15: return "0-0"
    if dr and u25 and gg: return "1-1"
    if dr and o35: return "2-2 (or higher)"
    if hw and u15: return "1-0"
    if aw and u15: return "0-1"
    if hw and u25 and o15 and ng: return "2-0"
    if aw and u25 and o15 and ng: return "0-2"
    if hw and o25 and u35 and gg: return "2-1"
    if aw and o25 and u35 and gg: return "1-2"
    if hw and o25 and u35 and ng: return "3-0"
    if aw and o25 and u35 and ng: return "0-3"
    
    return None

def load_patterns(filepath: str) -> dict:
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
    except:
        return {}
    
    lookup = {}
    for row in data:
        # Require minimum confidence and sample size
        if row['occurrences'] < 10:
            continue
            
        key = (row['home'], row['away'], row['home_tier'], row['away_tier'])
        lookup[key] = row
    return lookup

def get_live_tiers() -> dict:
    standings_data = msport_api.get_standings()
    if not standings_data:
        return {}
        
    standings_list = msport_api.extract_standings_table(standings_data)
    tiers = {}
    for team in standings_list:
        name = team.get("teamName")
        rank = team.get("rank")
        if name and rank is not None:
            tiers[name] = (get_tier(rank), get_micro_tier(rank))
    return tiers

def run_predictions():
    logger.info("Loading standing patterns...")
    macro_patterns = load_patterns(PATTERNS_FILE)
    micro_patterns = load_patterns(MICRO_PATTERNS_FILE)

    logger.info("Fetching live standings and upcoming events...")
    live_tiers = get_live_tiers()
    if not live_tiers:
        logger.error("Could not fetch live standings.")
        return
        
    events = msport_api.get_event_list()
    if not events:
        logger.error("Could not fetch events.")
        return

    upcoming_md = msport_api.find_upcoming_match_day(events)
    if not upcoming_md:
        logger.info("No upcoming matchday found.")
        return

    md_num = upcoming_md.get("matchDay")
    
    # Anti-spam check
    state_file = "/tmp/last_standing_md.txt"
    try:
        with open(state_file, "r") as f:
            last_md = int(f.read().strip())
    except:
        last_md = -1
        
    if md_num == last_md:
        logger.info(f"Already posted picks for Matchday {md_num}. Skipping.")
        return

    matches = upcoming_md.get("events", [])
    
    picks = []
    
    for match in matches:
        home = match.get("homeTeam")
        away = match.get("awayTeam")
        
        home_t_data = live_tiers.get(home)
        away_t_data = live_tiers.get(away)
        
        if not home_t_data or not away_t_data:
            continue
            
        home_tier, home_micro = home_t_data
        away_tier, away_micro = away_t_data
        
        macro_key = (home, away, home_tier, away_tier)
        micro_key = (home, away, home_micro, away_micro)
        
        macro_row = macro_patterns.get(macro_key, {})
        micro_row = micro_patterns.get(micro_key, {})

        confluence_picks = []
        micro_picks = []
        macro_picks = []

        markets = [
            ('Under 1.5', 'w_u15_rate'), ('Over 1.5', 'w_o15_rate'),
            ('Under 2.5', 'w_u25_rate'), ('Over 2.5', 'w_o25_rate'),
            ('Under 3.5', 'w_u35_rate'), ('Over 3.5', 'w_o35_rate'),
            ('GG (BTTS)', 'w_gg_rate'),
            ('Home Win (1)', 'w_1_rate'), ('Draw (X)', 'w_x_rate'), ('Away Win (2)', 'w_2_rate')
        ]

        # Evaluate Confluence
        for pick_name, rate_key in markets:
            mac_r = macro_row.get(rate_key, 0)
            mic_r = micro_row.get(rate_key, 0)

            if mac_r >= 0.80 and mic_r >= 0.80:
                confluence_picks.append((pick_name, mac_r, mic_r))
            elif mic_r >= 0.85:
                micro_picks.append((pick_name, mic_r))
            elif mac_r >= 0.85:
                macro_picks.append((pick_name, mac_r))

        # Check Chaos Trap Blacklist
        chaos_trap = False
        trap_reason = ""
        if (home_tier, away_tier) in [("T3", "T2"), ("T1", "T3"), ("T2", "T1")]:
            chaos_trap = True
            trap_reason = f"Macro Trap ({home_tier} vs {away_tier})"
        elif (home_micro, away_micro) in [("E", "D"), ("B", "A"), ("C", "A")]:
            chaos_trap = True
            trap_reason = f"Micro Trap ({home_micro} vs {away_micro})"
        elif (home, away) in [("Everton", "Manchester Blue"), ("Fulham", "West Ham"), ("Wolverhampton", "Tottenham")]:
            chaos_trap = True
            trap_reason = "Specific Team Chaos"

        if confluence_picks or micro_picks or macro_picks:
            match_header = f"⚔️ **{home}** vs **{away}**"
            picks.append(match_header)
            
            if chaos_trap:
                picks.append(f"   ⚠️ **[CHAOS TRAP WARNING]** Do not bet heavily. MSport RNG Target: {trap_reason}")
            
            # Use Micro for exact score and blindspots since it's the most granular
            target_row = micro_row if micro_row else macro_row
            exact_score = infer_exact_score(target_row)
            if exact_score:
                picks.append(f"   ↳ 🔮 **EXACT SCORE PREDICTION: {exact_score}**")
                
            if target_row.get('w_o25_rate', 0) >= 0.80 and target_row.get('w_u35_rate', 0) >= 0.80:
                picks.append("   🛡️ **BLINDSPOT COVER**: Play Under 3.5 (75% Safe) or Over 1.5 (73% Safe)")
            elif target_row.get('w_gg_rate', 0) >= 0.80 and target_row.get('w_u25_rate', 0) >= 0.80:
                picks.append("   🛡️ **BLINDSPOT COVER**: Play Under 3.5 (77% Safe)")
            elif target_row.get('w_1_rate', 0) >= 0.80 and target_row.get('w_u25_rate', 0) >= 0.80:
                picks.append("   🛡️ **BLINDSPOT COVER**: Play 1X (Home or Draw) (75% Safe)")
            elif target_row.get('w_2_rate', 0) >= 0.80 and target_row.get('w_u25_rate', 0) >= 0.80:
                picks.append("   🛡️ **BLINDSPOT COVER**: Play X2 (Draw or Away) (65% Safe)")
            elif target_row.get('w_gg_rate', 0) >= 0.80 and target_row.get('w_o25_rate', 0) >= 0.80:
                picks.append("   🛡️ **BLINDSPOT COVER**: Play Over 1.5 (73% Safe)")

            for pick, mac_r, mic_r in confluence_picks:
                picks.append(f"   ↳ 🥇 **[CONFLUENCE LOCK] {pick}**  •  Macro: {mac_r*100:.1f}% | Micro: {mic_r*100:.1f}%")
            
            for pick, mic_r in micro_picks:
                picks.append(f"   ↳ 🥈 **[MICRO LOCK] {pick}**  •  {mic_r*100:.1f}%")

            for pick, mac_r in macro_picks:
                picks.append(f"   ↳ 🥉 **[MACRO LOCK] {pick}**  •  {mac_r*100:.1f}%")

            picks.append("") # Empty line for spacing
                             
    if picks:
        message = f"🚨 **VFL CONDITIONAL LOCKS** | Matchday {md_num} 🚨\n\n"
        message += "\n".join(picks)
        
        logger.info("Sending picks to Discord...")
        subprocess.run(
            ["/home/ubuntu/.local/bin/hermes", "send", "--to", DISCORD_TARGET, message],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info("Sent successfully.")
        
        # Save state so we don't spam
        with open(state_file, "w") as f:
            f.write(str(md_num))
            
    else:
        logger.info(f"No high-confidence pattern locks found for Matchday {md_num}.")

if __name__ == "__main__":
    run_predictions()

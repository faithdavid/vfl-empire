#!/usr/bin/env python3
"""
VFL Intelligence Bridge — Connects ALL research streams into the Engine Predictor
"""
import json, os, math, sys
from collections import defaultdict

# Paths
BASE = os.path.expanduser('~/faith-workspace/vfl-complete-data')
PATTERN_RULES_PATH = os.path.join(BASE, 'analysis/pattern_rules.json')
H2H_PLAYBOOK_PATH = os.path.join(BASE, 'analysis/h2h_playbook.md')
H2H_MATCHUPS_PATH = os.path.join(BASE, 'analysis/h2h_matchup_patterns.json')
MISS_REPORTS_DIR = os.path.join(BASE, 'analysis/miss_reports')
INTEL_OUTPUT_PATH = os.path.join(BASE, 'analysis/unified_intel.json')
SIM_CONSTRAINTS_PATH = os.path.expanduser(
    "~/faith-workspace/vfl-complete-data/analysis/simulation_constraints.json"
)

# Ensure the bridge's scripts directory is on sys.path for sibling imports
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

def load_clara_patterns():
    """Load Clara's miss analysis patterns"""
    try:
        with open(PATTERN_RULES_PATH) as f:
            return json.load(f)
    except: return {}

def load_latest_miss_report():
    """Get the most recent Clara miss analysis"""
    try:
        with open(os.path.join(MISS_REPORTS_DIR, 'latest.json')) as f:
            return json.load(f)
    except: return {}

def load_h2h_matchups():
    """Load H2H matchup patterns"""
    try:
        with open(H2H_MATCHUPS_PATH) as f:
            return json.load(f)
    except: return {}

def parse_h2h_into_edges(h2h):
    """Extract value edges from H2H matchup analysis"""
    edges = []
    
    if isinstance(h2h, dict):
        # Structure: odds_adjusted_h2h is a team-by-team matrix
        # Each team -> opponent -> {when_home, when_away, avg_brier_score, ...}
        odds_matrix = h2h.get('odds_adjusted_h2h', {})
        if odds_matrix:
            for home_team, opponents in odds_matrix.items():
                if not isinstance(opponents, dict): continue
                for away_team, data in opponents.items():
                    if not isinstance(data, dict): continue
                    # Check both home and away fixtures for edges
                    when_home = data.get('when_home', {})
                    when_away = data.get('when_away', {})
                    
                    if isinstance(when_home, dict):
                        actual = when_home.get('actual_win_pct', 50)
                        implied = when_home.get('implied_win_pct', 50)
                        edge = actual - implied
                        if abs(edge) > 10:
                            edges.append({
                                'fixture': f"{home_team} vs {away_team} (home)",
                                'edge_pct': round(edge, 1),
                                'type': 'ODDS_ADJUSTED',
                                'actual': actual,
                                'implied': implied,
                                'matches': when_home.get('matches', 0)
                            })
                    
                    if isinstance(when_away, dict):
                        actual = when_away.get('actual_win_pct', 50)
                        implied = when_away.get('implied_win_pct', 50)
                        edge = actual - implied
                        if abs(edge) > 10:
                            edges.append({
                                'fixture': f"{home_team} at {away_team} (away)",
                                'edge_pct': round(edge, 1),
                                'type': 'ODDS_ADJUSTED',
                                'actual': actual,
                                'implied': implied,
                                'matches': when_away.get('matches', 0)
                            })
        
        # Patterns
        patterns_section = h2h.get('patterns', {})
        all_patterns = patterns_section.get('all_patterns', []) if isinstance(patterns_section, dict) else []
        for p in all_patterns:
            if isinstance(p, dict):
                ptype = p.get('type', '')
                if 'value' in ptype.lower() or 'edge' in ptype.lower():
                    edges.append({
                        'fixture': p.get('fixture', p.get('description', '')),
                        'edge_pct': float(p.get('value', p.get('edge', 0))),
                        'type': 'PATTERN'
                    })
        
        # Tier upset analysis
        tier_analysis = h2h.get('tier_upset_analysis', {})
        tier_summary = tier_analysis.get('tier_pair_summary', {}) if isinstance(tier_analysis, dict) else {}
        for tier, data in tier_summary.items():
            if isinstance(data, dict):
                lower_wins = data.get('lower_tier_wins', 0)
                total = data.get('total_matches', 1)
                upset_rate = lower_wins / total * 100 if total else 0
                if upset_rate > 25:
                    edges.append({
                        'fixture': f"{tier.replace('_', ' vs ')}",
                        'edge_pct': round(upset_rate, 1),
                        'type': 'TIER_UPSET',
                        'matches': total
                    })
        
        # Specific upset matchups
        specific = tier_analysis.get('specific_upset_matchups', []) if isinstance(tier_analysis, dict) else []
        for s in specific:
            if isinstance(s, dict):
                edges.append({
                    'fixture': f"{s.get('lower_tier_team', '?')} vs {s.get('higher_tier_team', '?')}",
                    'edge_pct': float(s.get('upset_pct', 0)),
                    'type': 'SPECIFIC_UPSET',
                    'matches': s.get('matches', 0)
                })
    
    elif isinstance(h2h, list):
        for item in h2h[:100]:
            if isinstance(item, dict):
                edges.append({
                    'fixture': f"{item.get('home','?')} vs {item.get('away','?')}",
                    'edge_pct': float(item.get('home_win_pct', 50)) - 50,
                    'type': 'H2H_EDGE'
                })
    
    return edges

def build_unified_intel():
    """Merge all streams into actionable intelligence"""
    patterns = load_clara_patterns()
    miss_report = load_latest_miss_report()
    h2h = load_h2h_matchups()
    
    intel = {
        'version': '2.0',
        'generated': __import__('datetime').datetime.now().isoformat(),
        'streams': {
            'clara_misses': len(miss_report.get('misses', [])),
            'pattern_rules': len(patterns.get('team_specific_patterns', {})),
            'h2h_matchups': len(h2h.get('matchups', [])),
        }
    }
    
    # ====== TEAM-SPECIFIC CONSTRAINTS (from Clara) ======
    team_rules = patterns.get('team_specific_patterns', {})
    intel['team_constraints'] = {}
    
    # Build lookup: team_name -> {avoid_prediction, draw_bias, confidence_penalty}
    for team, info in team_rules.items():
        rule_text = info.get('rule', '')
        constraint = {
            'draw_bias': 'DRAW' in rule_text or 'draw' in rule_text.lower(),
            'draw_surprise_pct': info.get('draw_surprise_pct', 0),
            'home_trap': 'HOME_FAVORITE_TRAP' in rule_text,
            'home_fav_loss_pct': info.get('home_favorite_loss_pct', 0),
            'away_strong': 'away' in rule_text.lower() and 'win' in rule_text.lower(),
            'upset_specialist': 'UPSET' in rule_text,
            'unreliable': 'UNRELIABLE' in rule_text or 'Never trust' in rule_text,
        }
        
        # Parse rule for actionable penalties
        if constraint['home_trap']:
            constraint['home_confidence_penalty'] = -20
        if constraint['draw_bias']:
            constraint['draw_boost'] = 10
        if constraint['upset_specialist']:
            constraint['t1_discount'] = 15  # discount T1 favorite by 15%
        
        intel['team_constraints'][team.upper()] = constraint
    
    # ====== CONFIDENCE CALIBRATION (from Clara) ======
    calib = patterns.get('confidence_calibration', {})
    intel['confidence_calibration'] = {}
    for bucket, data in calib.items():
        # Parse bucket name like "55-70_pct"
        if '_pct' in bucket:
            try:
                low, high = bucket.replace('_pct', '').split('-')
                actual = data.get('accuracy', 0)
                intel['confidence_calibration'][f'{low}-{high}'] = {
                    'actual_accuracy': actual,
                    'penalty': round(actual - (int(low) + int(high)) / 2, 1)
                }
            except:
                pass
    
    # ====== H2H VALUE EDGES (from playbook) ======
    intel['value_edges'] = []
    
    # From pattern_rules
    edges_from_rules = patterns.get('h2h_derived_rules', [])
    for edge in edges_from_rules:
        if edge.get('type') == 'VALUE_EDGE':
            try:
                edge_val = float(edge['rule'].split('+')[1].split('%')[0]) if '+%' in edge.get('rule', '') else 0
                intel['value_edges'].append({
                    'fixture': edge.get('fixture', ''),
                    'edge_pct': edge_val,
                    'type': 'H2H_DERIVED'
                })
            except: pass
    
    # From H2H matchup file
    h2h_edges = parse_h2h_into_edges(h2h)
    intel['value_edges'].extend(h2h_edges)
    
    # Remove duplicates and sort
    seen = set()
    unique_edges = []
    for e in sorted(intel['value_edges'], key=lambda x: -abs(x.get('edge_pct', 0))):
        key = e.get('fixture', '')
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)
    intel['value_edges'] = unique_edges[:20]  # Top 20
    
    # ====== MISS TYPE DISTRIBUTION ======
    miss_types = patterns.get('miss_type_distribution', {})
    intel['miss_type_distribution'] = miss_types
    
    # ====== ACTIONABLE CONSTRAINTS ======
    intel['actionable_constraints'] = patterns.get('actionable_constraints', [])
    
    # ====== H2H PLAYBOOK RULES ======
    # Extract the top edges from the playbook
    intel['top_h2h_edges'] = []
    if h2h:
        matchups = h2h.get('matchups', []) if isinstance(h2h, dict) else h2h if isinstance(h2h, list) else []
        for m in matchups[:20]:
            if isinstance(m, dict):
                intel['top_h2h_edges'].append({
                    'home': m.get('home', ''),
                    'away': m.get('away', ''),
                    'home_win_pct': m.get('home_win_pct', 0),
                    'away_win_pct': m.get('away_win_pct', 0),
                    'draw_pct': m.get('draw_pct', 0),
                    'n': m.get('matches', 0)
                })
    
    return intel

# ── Engine Regime Fusion ───────────────────────────────────────────────────────

def fuse_with_engine_context(intel_dict: dict, engine_regime_dict: dict) -> dict:
    """Fuse unified intelligence with engine regime context.

    Fuses the engine's current scoring regime into the intelligence dict so
    that the predictor can apply recency-aware adjustments.

    Adjustment rules:
      - OFFENSIVE regime → boost O1.5 confidence by 5-10 across all fixtures
      - DEFENSIVE regime → boost U3.5 confidence by 5-10
      - Adds engine parameters to the output for downstream consumption

    Args:
        intel_dict: Unified intelligence dict from build_unified_intel()
        engine_regime_dict: Dict from EngineRegimeDetector.get_current_regime()

    Returns:
        The fused intel dict with engine regime info merged in.
    """
    # Deep copy to avoid mutating the original
    fused = json.loads(json.dumps(intel_dict))
    regime = engine_regime_dict.get("regime", "NEUTRAL")
    avg_goals = engine_regime_dict.get("avg_goals", 2.5)
    trend = engine_regime_dict.get("trend", "stable")

    # Compute regime-based boosts
    o15_boost = 0
    u35_boost = 0

    if regime == "OFFENSIVE":
        o15_boost = max(5, min(10, int((avg_goals - 2.5) * 20)))  # 5-10 range
    elif regime == "DEFENSIVE":
        u35_boost = max(5, min(10, int((3.0 - avg_goals) * 20)))  # 5-10 range
    elif regime == "NEUTRAL":
        # Small adjustments based on trend
        if trend == "rising":
            o15_boost = 3
        elif trend == "falling":
            u35_boost = 3

    fused["engine_regime"] = {
        "regime": regime,
        "trend": trend,
        "avg_goals": avg_goals,
        "n_matches": engine_regime_dict.get("n_matches", 0),
        "u35_rate": engine_regime_dict.get("u35_rate", 70.0),
        "o15_rate": engine_regime_dict.get("o15_rate", 75.0),
        "season_id": engine_regime_dict.get("season_id", ""),
        "adjustments": {
            "over_1_5_boost": o15_boost,
            "under_3_5_boost": u35_boost,
        },
    }

    # Apply fixture-level adjustments as a hint for the predictor
    fused["regime_adjustments"] = {
        "o15_confidence_boost": o15_boost,
        "u35_confidence_boost": u35_boost,
    }

    return fused


# ── Simulation Constraints Loader ──────────────────────────────────────────────

def load_simulation_constraints() -> dict:
    """Load matchday template constraints from simulation_constraints.json."""
    try:
        with open(SIM_CONSTRAINTS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


# ── Live Context Generator ─────────────────────────────────────────────────────

def generate_live_context(home: str, away: str, season_id: str = None) -> dict:
    """Generate a unified live context for a specific fixture.

    Gathers insight from multiple concurrent streams:
      - Engine regime (current scoring parameters)
      - Team constraints (from Clara's pattern analysis)
      - H2H value edges
      - Simulation constraints / matchday template

    Args:
        home: Home team name
        away: Away team name
        season_id: Optional season identifier for season-form queries

    Returns:
        Dict with unified context for this specific fixture.
    """
    context = {
        "fixture": f"{home} vs {away}",
        "home": home,
        "away": away,
        "season_id": season_id or "",
    }

    # 1. Engine regime context
    try:
        from vfl_engine_detector import EngineRegimeDetector
        detector = EngineRegimeDetector()
        regime = detector.get_current_regime()
        context["engine_regime"] = regime
        context["regime_adjustments"] = {
            "o15_boost": detector.get_regime_adjustment("O1.5", regime),
            "u35_boost": detector.get_regime_adjustment("U3.5", regime),
        }
    except Exception as e:
        context["engine_regime"] = {"regime": "NEUTRAL", "error": str(e)}
        context["regime_adjustments"] = {"o15_boost": 0, "u35_boost": 0}

    # 2. Team constraints from unified intel
    try:
        intel = build_unified_intel()
        hk = home.upper().strip()
        ak = away.upper().strip()
        tc = intel.get("team_constraints", {})
        context["home_constraints"] = tc.get(hk, {})
        context["away_constraints"] = tc.get(ak, {})
        context["top_h2h_edges"] = intel.get("top_h2h_edges", [])[:5]
    except Exception:
        context["home_constraints"] = {}
        context["away_constraints"] = {}
        context["top_h2h_edges"] = []

    # 3. Simulation constraints / matchday template
    try:
        sim = load_simulation_constraints()
        context["simulation_constraints"] = {
            "win_ceiling": sim.get("win_ceiling_governor", {}),
            "draw_floor": sim.get("draw_floor_governor", {}),
            "home_governor": sim.get("home_governor", {}),
        }
    except Exception:
        context["simulation_constraints"] = {}

    # 4. H2H value edges for this fixture
    try:
        h2h_base = load_h2h_matchups()
        h2h_edges = parse_h2h_into_edges(h2h_base)
        fixture_edges = [
            e for e in h2h_edges
            if home.upper() in e.get("fixture", "").upper()
            and away.upper() in e.get("fixture", "").upper()
        ]
        context["fixture_h2h_edges"] = fixture_edges[:3]
    except Exception:
        context["fixture_h2h_edges"] = []

    return context


# ── Main Entry Point ───────────────────────────────────────────────────────────

def main():
    intel = build_unified_intel()
    
    # ── Engine regime fusion ──
    try:
        from vfl_engine_detector import EngineRegimeDetector
        detector = EngineRegimeDetector()
        regime = detector.get_current_regime()
        intel = fuse_with_engine_context(intel, regime)
    except Exception as e:
        print(f"[WARN] Engine regime fusion skipped: {e}")
        intel["engine_regime"] = {"regime": "NEUTRAL", "error": str(e)}
    
    with open(INTEL_OUTPUT_PATH, 'w') as f:
        json.dump(intel, f, indent=2)
    
    # Print summary for cron delivery
    print(f"{'='*60}")
    print(f"🧠 VFL INTELLIGENCE BRIDGE — Unified Intel")
    print(f"{'='*60}")
    
    streams = intel['streams']
    print(f"\n📡 Streams connected:")
    print(f"  Clara misses: {streams['clara_misses']} analyzed")
    print(f"  Team patterns: {streams['pattern_rules']} rules")
    print(f"  H2H matchups: {streams['h2h_matchups']} pairings")
    
    # ── Engine regime proof ──
    engine = intel.get("engine_regime", {})
    if engine:
        regime_label = engine.get("regime", "NEUTRAL")
        trend = engine.get("trend", "stable")
        avg_goals = engine.get("avg_goals", "?")
        n_matches = engine.get("n_matches", 0)
        print(f"\n🔧 Engine: {regime_label} | Trend: {trend} | Last {n_matches} matches: {avg_goals} avg goals")
        adj = engine.get("adjustments", {})
        o15_b = adj.get("over_1_5_boost", 0)
        u35_b = adj.get("under_3_5_boost", 0)
        if o15_b or u35_b:
            print(f"  Regime adjustments: O1.5 {o15_b:+d} | U3.5 {u35_b:+d}")
    
    constraints = intel.get('team_constraints', {})
    print(f"\n🚫 Team-specific constraints:")
    for team, c in sorted(constraints.items()):
        flags = []
        if c.get('home_trap'): flags.append('HOME_TRAP')
        if c.get('draw_bias'): flags.append('DRAW_BIAS')
        if c.get('upset_specialist'): flags.append('UPSET_SPEC')
        if c.get('unreliable'): flags.append('UNRELIABLE')
        if flags:
            print(f"  {team:20s}: {' | '.join(flags)}")
    
    calib = intel.get('confidence_calibration', {})
    print(f"\n📊 Confidence calibration:")
    for bucket, data in sorted(calib.items()):
        penalty = data.get('penalty', 0)
        arrow = '🔴' if penalty < -5 else ('🟢' if penalty > 5 else '➖')
        print(f"  {bucket:>8s}%: actual={data['actual_accuracy']:.1f}% {arrow}")
    
    edges = intel.get('value_edges', [])
    print(f"\n💰 Top value edges from H2H:")
    for e in sorted(edges, key=lambda x: -x.get('edge_pct', 0))[:5]:
        print(f"  {e['fixture']}: +{e['edge_pct']:.1f}% edge")
    
    print(f"\n✅ Unified intel saved to {INTEL_OUTPUT_PATH}")
    return 0

if __name__ == '__main__':
    exit(main())

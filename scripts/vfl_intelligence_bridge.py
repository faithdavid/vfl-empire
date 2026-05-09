#!/usr/bin/env python3
"""
VFL Intelligence Bridge — Connects ALL research streams into the Engine Predictor
"""
import json, os, math
from collections import defaultdict

# Paths
BASE = os.path.expanduser('~/Documents/Projects/vfl-data')
PATTERN_RULES_PATH = os.path.join(BASE, 'analysis/pattern_rules.json')
H2H_PLAYBOOK_PATH = os.path.join(BASE, 'analysis/h2h_playbook.md')
H2H_MATCHUPS_PATH = os.path.join(BASE, 'analysis/h2h_matchup_patterns.json')
MISS_REPORTS_DIR = os.path.join(BASE, 'analysis/miss_reports')
INTEL_OUTPUT_PATH = os.path.join(BASE, 'analysis/unified_intel.json')

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

def main():
    intel = build_unified_intel()
    
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

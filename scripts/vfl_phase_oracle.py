import json
import numpy as np

class PhaseAwareOracle:
    def __init__(self, db_path='/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks.json'):
        self.locks_db = {}
        self.load_database(db_path)
        
        # Compounding Management
        self.current_streak = 0
        self.target_streak = 12 # Default to 12 as discussed, can be adjusted to 16 later
        self.initial_stake = 50.0
        self.current_bankroll = self.initial_stake

    def load_database(self, db_path):
        try:
            with open(db_path, 'r') as f:
                locks_list = json.load(f)
                
            for lock in locks_list:
                # Key: (Home, Away, Home_Tier, Away_Tier, Phase)
                key = (lock['home'], lock['away'], lock['home_tier'], lock['away_tier'], lock['phase'])
                self.locks_db[key] = lock['lock']
            print(f"✅ Oracle Database loaded with {len(self.locks_db)} algorithmic locks.")
        except Exception as e:
            print(f"❌ Failed to load locks database: {e}")

    def reset_compounding_cycle(self):
        """Resets the bankroll after hitting the target streak."""
        profit = self.current_bankroll - self.initial_stake
        print(f"\n🎉 TARGET STREAK HIT ({self.target_streak}/{self.target_streak})!")
        print(f"💰 Cashing out profit: ₦{profit:,.2f}")
        print("🔄 Resetting cycle back to initial stake...\n")
        self.current_streak = 0
        self.current_bankroll = self.initial_stake

    def predict_matchday(self, matchday, fixtures, standings_dict):
        """
        Takes the current matchday, the 8-10 fixtures, and the current standings.
        Returns a list of high-confidence predictions to bet on.
        """
        # 1. Calculate the current engine phase
        current_phase = int(np.ceil(matchday / 2.0))
        
        predictions = []

        # 2. Scan all live fixtures
        for match in fixtures:
            home_team = match['home']
            away_team = match['away']
            
            # Get current tiers from standings
            h_tier = standings_dict.get(home_team, 'UNKNOWN')
            a_tier = standings_dict.get(away_team, 'UNKNOWN')
            
            # 3. Query the Oracle Database
            lookup_key = (home_team, away_team, h_tier, a_tier, current_phase)
            
            if lookup_key in self.locks_db:
                lock_type = self.locks_db[lookup_key]
                pred_str = "HOME WIN" if lock_type == 'hw' else "AWAY WIN" if lock_type == 'aw' else "DRAW"
                
                prediction = {
                    'fixture': f"{home_team} vs {away_team}",
                    'phase': current_phase,
                    'tiers': f"{h_tier} v {a_tier}",
                    'prediction': pred_str,
                    'recommended_stake': self.current_bankroll
                }
                predictions.append(prediction)

        return predictions

    def process_match_result(self, won, odds_won):
        """Called after a match finishes to update the compounding bankroll."""
        if won:
            self.current_streak += 1
            self.current_bankroll = self.current_bankroll * odds_won
            print(f"✅ WON! Streak: {self.current_streak}/{self.target_streak} | New Bankroll: ₦{self.current_bankroll:,.2f}")
            
            if self.current_streak >= self.target_streak:
                self.reset_compounding_cycle()
        else:
            print("❌ LOST! Algorithmic failure detected. Resetting bankroll.")
            self.current_streak = 0
            self.current_bankroll = self.initial_stake


if __name__ == "__main__":
    # Quick Test of the Oracle Skeleton
    oracle = PhaseAwareOracle()
    
    # Mocking Matchday 17 (Phase 9) from our backtest
    mock_standings = {'Manchester Blue': 'T1', 'Everton': 'T2'}
    mock_fixtures = [{'home': 'Manchester Blue', 'away': 'Everton'}]
    
    print("\n🔮 Oracle scanning Matchday 17...")
    preds = oracle.predict_matchday(17, mock_fixtures, mock_standings)
    
    for p in preds:
        print(f"🚨 LOCK FOUND: {p['fixture']} ({p['tiers']}) -> {p['prediction']}")
        print(f"💸 Recommended Stake: ₦{p['recommended_stake']:,.2f}")

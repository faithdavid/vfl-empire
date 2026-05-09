"""
VFL Betting Game for MuZero — uses our 42K consolidated results.
Each episode: MuZero sees a match's odds, decides HOME/DRAW/AWAY/SKIP.
Reward: +1 correct bet, -1 wrong bet, 0 for skip.
"""

import datetime
import pathlib
import json
import numpy
import torch
import os
from .abstract_game import AbstractGame

class MuZeroConfig:
    def __init__(self):
        self.seed = 0
        self.max_num_gpus = None

        ### Game
        self.observation_shape = (6, 1, 1)  # 6 features as 1x1 "image"
        self.action_space = list(range(4))  # 0=HOME, 1=DRAW, 2=AWAY, 3=SKIP
        self.players = list(range(1))
        self.stacked_observations = 0

        # Evaluate
        self.muzero_player = 0
        self.opponent = None

        ### Self-Play
        self.num_workers = 4
        self.selfplay_on_gpu = False
        self.max_moves = 1  # One bet per match
        self.num_simulations = 50
        self.discount = 0.997
        self.temperature_threshold = None

        self.root_dirichlet_alpha = 0.25
        self.root_exploration_fraction = 0.25
        self.pb_c_base = 19652
        self.pb_c_init = 1.25

        ### Network
        self.network = "fullyconnected"
        self.support_size = 10
        self.encoding_size = 64
        self.fc_representation_layers = [64]
        self.fc_dynamics_layers = [64]
        self.fc_reward_layers = [32]
        self.fc_value_layers = [32]
        self.fc_policy_layers = [32]

        ### Training
        self.results_path = pathlib.Path(__file__).resolve().parents[1] / "results" / pathlib.Path(__file__).stem / datetime.datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        self.save_model = True
        self.training_steps = 50000
        self.batch_size = 64
        self.checkpoint_interval = 10
        self.value_loss_weight = 0.25
        self.train_on_gpu = torch.cuda.is_available()
        self.optimizer = "SGD"
        self.weight_decay = 1e-4
        self.momentum = 0.9
        self.lr_init = 0.01
        self.lr_decay_rate = 0.75
        self.lr_decay_steps = 150000

        ### Replay Buffer
        self.replay_buffer_size = 10000
        self.num_unroll_steps = 1
        self.td_steps = 1
        self.PER = True
        self.PER_alpha = 0.5
        self.use_last_model_value = True
        self.reanalyse_on_gpu = False

        self.self_play_delay = 0
        self.training_delay = 0
        self.ratio = None

    def visit_softmax_temperature_fn(self, trained_steps):
        if trained_steps < 500e3:
            return 1.0
        elif trained_steps < 750e3:
            return 0.5
        else:
            return 0.25


class Game(AbstractGame):
    def __init__(self, seed=None):
        self.env = VFLBetting(seed)

    def step(self, action):
        observation, reward, done = self.env.step(action)
        return observation, reward, done

    def to_play(self):
        return self.env.to_play()

    def legal_actions(self):
        return self.env.legal_actions()

    def reset(self):
        return self.env.reset()

    def render(self):
        self.env.render()

    def human_to_action(self):
        choice = input("Enter action (0=HOME, 1=DRAW, 2=AWAY, 3=SKIP): ")
        while choice not in [str(a) for a in self.legal_actions()]:
            choice = input("Enter 0, 1, 2, or 3: ")
        return int(choice)

    def action_to_string(self, action_number):
        return {0: "HOME", 1: "DRAW", 2: "AWAY", 3: "SKIP"}.get(action_number, "?")


class VFLBetting:
    """VFL betting environment using our consolidated data."""

    def __init__(self, seed):
        self.random = numpy.random.RandomState(seed)
        self.matches = self._load_data()
        self.idx = 0
        self.current_match = None

    def _load_data(self):
        """Load odds from ALL sources + use Poisson simulator for infinite training data."""
        matches = []
        
        # Source 1: Consolidated joined data (real odds + outcomes)
        joined_path = os.path.expanduser("/tmp/all_consolidated_joined.json")
        odds_path = os.path.expanduser("/tmp/all_consolidated_odds.json")
        
        try:
            with open(joined_path) as f:
                joined = json.load(f)
            matches.extend(joined)
            print(f"Loaded {len(joined)} real joined matches")
        except: pass
        
        # Source 2: All odds entries (use Poisson to generate outcomes)
        try:
            with open(odds_path) as f:
                all_odds = json.load(f)
            # Add each odds entry as a template for the simulator
            for o in all_odds:
                matches.append({
                    'odds_h': o['odds_h'],
                    'odds_d': o['odds_d'],
                    'odds_a': o['odds_a'],
                    'simulate': True,  # Flag for Poisson simulation
                })
            print(f"Loaded {len(all_odds)} odds templates for simulation")
        except Exception as e:
            print(f"Could not load odds: {e}")
        
        # Source 3: All HAR results (use odds derived from implied probabilities)
        results_path = os.path.expanduser("/tmp/all_consolidated_results.json")
        try:
            with open(results_path) as f:
                results = json.load(f)
            # For results without odds, derive approximate odds from outcome
            # This gives us more real data points
            known = set((m.get('odds_h'), m.get('odds_h')) for m in matches if 'odds_h' in m)
            for r in results[:10000]:  # Use first 10K
                key = (r.get('odds_h'), r.get('odds_h'))
                if key in known or 'odds_h' in r:
                    continue
                # Derive approximate odds from global averages
                oh = 2.5  # Default
                matches.append({
                    'odds_h': oh,
                    'odds_d': 3.3,
                    'odds_a': 2.8,
                    'simulate': True,
                })
        except: pass
        
        if len(matches) < 100:
            print(f"Only {len(matches)} matches, generating synthetic...")
            matches = self._generate_synthetic(50000)
        
        print(f"Total training pool: {len(matches)} matches")
        return matches

    def _generate_synthetic(self, n):
        matches = []
        for _ in range(n):
            hs = self.random.uniform(0.3, 1.5)
            as_ = self.random.uniform(0.3, 1.5)
            matches.append({'odds_h': round(2.0,2), 'odds_d': round(3.3,2), 'odds_a': round(2.8,2), 'simulate': True})
        return matches

    def _simulate_match(self, oh, od, oa):
        """Simulate match using Poisson engine model."""
        ti = 1/oh + 1/od + 1/oa
        ph, pa = 1/oh/ti, 1/oa/ti
        hs = ph / (ph + pa) * 2
        as_ = pa / (ph + pa) * 2
        lh = 1.437 * hs
        la = 1.142 * as_
        hg = self.random.poisson(lh)
        ag = self.random.poisson(la)
        if hg > ag: outcome = 0
        elif hg < ag: outcome = 2
        else: outcome = 1
        return outcome, hg, ag

    def to_play(self):
        return 0

    def reset(self):
        # Shuffle and start new epoch
        self.random.shuffle(self.matches)
        self.idx = 0
        self.current_match = self.matches[0]
        return self.get_observation()

    def step(self, action):
        """Place a bet. Uses Poisson simulation for synthetic matches."""
        m = self.current_match
        
        # Simulate outcome if needed
        if m.get('simulate'):
            outcome, hg, ag = self._simulate_match(m['odds_h'], m['odds_d'], m['odds_a'])
        else:
            outcome = m.get('outcome')
            if outcome is None:
                fh, fa = m.get('ft_home', 0), m.get('ft_away', 0)
                if fh > fa: outcome = 0
                elif fh < fa: outcome = 2
                else: outcome = 1
        
        # Calculate reward
        if action == 3:  # SKIP
            reward = 0.0
        elif action == outcome:  # Correct
            odds_map = {0: m['odds_h'], 1: m['odds_d'], 2: m['odds_a']}
            reward = min(odds_map.get(action, 2.0) - 1.0, 5.0)
        else:  # Wrong
            reward = -1.0
        
        # Move to next match
        self.idx += 1
        done = self.idx >= len(self.matches)
        if not done:
            self.current_match = self.matches[self.idx]
        
        return self.get_observation(), reward, done

    def get_observation(self):
        """Encode match as observation tensor."""
        m = self.current_match
        oh, od, oa = m['odds_h'], m['odds_d'], m['odds_a']
        ti = 1/oh + 1/od + 1/oa
        ph, pd_, pa = 1/oh/ti, 1/od/ti, 1/oa/ti
        
        return [
            numpy.full((1, 1), ph, dtype="float32"),     # Home prob
            numpy.full((1, 1), pd_, dtype="float32"),    # Draw prob
            numpy.full((1, 1), pa, dtype="float32"),     # Away prob
            numpy.full((1, 1), oh/10.0, dtype="float32"),# Home odds normalized
            numpy.full((1, 1), od/10.0, dtype="float32"),# Draw odds normalized
            numpy.full((1, 1), oa/10.0, dtype="float32"),# Away odds normalized
        ]

    def legal_actions(self):
        return [0, 1, 2, 3]

    def render(self):
        m = self.current_match
        print(f"Match: H:{m['odds_h']:.2f} D:{m['odds_d']:.2f} A:{m['odds_a']:.2f}")

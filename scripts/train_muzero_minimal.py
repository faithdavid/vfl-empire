"""
VFL Minimal MuZero — single worker, tiny network, runs on limited RAM.
"""
import datetime, pathlib, json, numpy as np, torch, os
from pathlib import Path
import sys
sys.path.insert(0, str(Path.home() / 'Documents/Projects/muzero-general'))
from games.abstract_game import AbstractGame

class MuZeroConfig:
    def __init__(self):
        self.seed = 0; self.max_num_gpus = None
        self.observation_shape = (6, 1, 1); self.action_space = list(range(4))
        self.players = list(range(1)); self.stacked_observations = 0
        self.muzero_player = 0; self.opponent = None
        self.num_workers = 1  # SINGLE worker to save RAM
        self.selfplay_on_gpu = False
        self.max_moves = 1; self.num_simulations = 10  # Fewer simulations
        self.discount = 0.997; self.temperature_threshold = None
        self.root_dirichlet_alpha = 0.25; self.root_exploration_fraction = 0.25
        self.pb_c_base = 19652; self.pb_c_init = 1.25
        self.network = "fullyconnected"; self.support_size = 5
        self.encoding_size = 16  # Tiny network
        self.fc_representation_layers = [16]
        self.fc_dynamics_layers = [16]
        self.fc_reward_layers = [8]
        self.fc_value_layers = [8]
        self.fc_policy_layers = [8]
        rp = pathlib.Path.home() / 'Documents/Projects/vfl-empire' / 'models' / 'muzero_minimal'
        self.results_path = str(rp)
        self.save_model = True; self.training_steps = 5000
        self.batch_size = 32; self.checkpoint_interval = 50
        self.value_loss_weight = 0.25
        self.train_on_gpu = False
        self.optimizer = "SGD"; self.weight_decay = 1e-4; self.momentum = 0.9
        self.lr_init = 0.01; self.lr_decay_rate = 0.75; self.lr_decay_steps = 15000
        self.replay_buffer_size = 2000; self.num_unroll_steps = 1; self.td_steps = 1
        self.PER = True; self.PER_alpha = 0.5
        self.use_last_model_value = True; self.reanalyse_on_gpu = False
        self.self_play_delay = 0; self.training_delay = 0; self.ratio = None
    def visit_softmax_temperature_fn(self, trained_steps):
        if trained_steps < 500e3: return 1.0
        elif trained_steps < 750e3: return 0.5
        else: return 0.25

class Game(AbstractGame):
    def __init__(self, seed=None): self.env = VFLBetting(seed)
    def step(self, act): return self.env.step(act)
    def to_play(self): return self.env.to_play()
    def legal_actions(self): return self.env.legal_actions()
    def reset(self): return self.env.reset()
    def render(self): self.env.render()
    def human_to_action(self):
        c = input("0=HOME 1=DRAW 2=AWAY 3=SKIP: ")
        while c not in [str(a) for a in self.legal_actions()]: c = input("0-3: ")
        return int(c)
    def action_to_string(self, a):
        return {0:"HOME",1:"DRAW",2:"AWAY",3:"SKIP"}.get(a,"?")

class VFLBetting:
    def __init__(self, seed):
        self.random = np.random.RandomState(seed)
        self.matches = self._load_data()
        self.idx = 0; self.current_match = None
    def _load_data(self):
        matches = []
        data_path = Path.home() / 'Documents/Projects/vfl-empire' / 'data' / 'consolidated' / 'all_consolidated_joined.json'
        if data_path.exists():
            data = json.load(open(data_path))
            for m in data[:500]:
                oh,od,oa = m.get('odds_h',0),m.get('odds_d',0),m.get('odds_a',0)
                out = m.get('outcome')
                if oh and od and oa and out is not None:
                    matches.append({'odds_h':oh,'odds_d':od,'odds_a':oa,'outcome':out})
        odds_path = Path.home() / 'Documents/Projects/vfl-empire' / 'data' / 'consolidated' / 'all_consolidated_odds.json'
        if odds_path.exists():
            data = json.load(open(odds_path))
            for m in data[:1500]:
                matches.append({'odds_h':m.get('odds_h',2.0),'odds_d':m.get('odds_d',3.3),
                               'odds_a':m.get('odds_a',2.8),'simulate':True})
        print(f"Loaded {len(matches)} matches")
        return matches
    def _simulate(self, oh, od, oa):
        ti = 1/oh+1/od+1/oa; ph,pa = 1/oh/ti,1/oa/ti
        hs=ph/(ph+pa)*2 if (ph+pa)>0 else 1; as_=pa/(ph+pa)*2 if (ph+pa)>0 else 1
        return 0 if self.random.poisson(1.437*hs) > self.random.poisson(1.142*as_) else 2
    def to_play(self): return 0
    def reset(self):
        self.random.shuffle(self.matches); self.idx = 0
        self.current_match = self.matches[0]; return self.get_observation()
    def step(self, action):
        m = self.current_match
        outcome = self._simulate(m["odds_h"],m["odds_d"],m["odds_a"]) if m.get("simulate") else m.get("outcome",0)
        if action == 3: reward = 0.0
        elif action == outcome: reward = min({0:m["odds_h"],1:m["odds_d"],2:m["odds_a"]}[action]-1.0, 5.0)
        else: reward = -1.0
        self.idx += 1; done = self.idx >= len(self.matches)
        if not done: self.current_match = self.matches[self.idx]
        return self.get_observation(), reward, done
    def get_observation(self):
        m=self.current_match; oh,od,oa=m["odds_h"],m["odds_d"],m["odds_a"]
        ti=1/oh+1/od+1/oa; ph,pd_,pa=1/oh/ti,1/od/ti,1/oa/ti
        return [np.full((1,1),ph,"f4"),np.full((1,1),pd_,"f4"),np.full((1,1),pa,"f4"),
                np.full((1,1),oh/10,"f4"),np.full((1,1),od/10,"f4"),np.full((1,1),oa/10,"f4")]
    def legal_actions(self): return [0,1,2,3]
    def render(self):
        m=self.current_match
        print(f'{m.get("home","?")} vs {m.get("away","?")}: {m["odds_h"]:.2f}/{m["odds_d"]:.2f}/{m["odds_a"]:.2f}')

if __name__ == "__main__":
    # Run training
    import sys
    sys.path.insert(0, str(Path.home() / 'Documents/Projects/muzero-general'))
    from muzero import MuZero
    
    config = MuZeroConfig()
    print(f"Config: {config.training_steps} steps, 1 worker, {config.num_simulations} sims, {config.encoding_size}-wide net")
    mz = MuZero(config)
    mz.train()
    print("Training complete!")

import sys
import os
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from dynamic_team_classifier import DynamicTeamClassifier

c = DynamicTeamClassifier()
print("Profiles keys:", list(c._profiles.keys()))
print("Weighted profiles keys:", list(c._weighted_profiles.keys()))

team = "Manchester Blue"
print(f"Profile for {team}:", c.get_team_profile(team))

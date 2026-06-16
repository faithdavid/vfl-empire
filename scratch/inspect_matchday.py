import sys, os, json
sys.path.insert(0, os.path.expanduser("~/faith-workspace/vfl-empire/services/common"))
from msport_client import get_match_day_info

info = get_match_day_info()
print(json.dumps(info, indent=2))

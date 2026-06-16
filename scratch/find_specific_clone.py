import json

def find_specific_match_clone():
    # Newcastle beat Man Blue 1-0 away in MD 4
    # Manchester Red and Chelsea draw 2-2 away in MD 4
    # Liverpool win 5-0 away at Fulham in MD 4
    
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    matches = []
    for s_name, seasons in data.items():
        fixes = seasons.get("4")
        if not fixes: continue
        
        sig = {}
        for fx in fixes:
            pair = tuple(sorted(fx["teams"].split(" vs ")))
            sig[pair] = fx["result"]
            
        # Check specific results
        if sig.get(tuple(sorted(["Manchester Blue", "Newcastle"]))) == "0-1" and \
           sig.get(tuple(sorted(["Fulham", "Liverpool"]))) == "0-5":
            matches.append(s_name)
            
    return matches

if __name__ == "__main__":
    matches = find_specific_match_clone()
    print(f"Seasons where Man Blue lost 0-1 to Newcastle AND Liverpool won 5-0 at Fulham (MD 4): {matches}")

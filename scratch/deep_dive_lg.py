import json

def analyze_lg_chelsea_md18():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    hits = 0
    total = 0
    o35_hits = 0
    
    for s_name, seasons in data.items():
        if "18" in seasons:
            for fix in seasons["18"]:
                if fix["teams"] == "London Guns vs Chelsea":
                    total += 1
                    if fix["total"] > 1: hits += 1
                    if fix["total"] > 3: o35_hits += 1
                    
    return {"total": total, "o15_hits": hits, "o35_hits": o35_hits}

if __name__ == "__main__":
    print(json.dumps(analyze_lg_chelsea_md18(), indent=2))

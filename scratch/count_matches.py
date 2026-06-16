import json

def count_matches():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    counts = []
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            counts.append(len(fixes))
            if len(counts) > 100: break
        if len(counts) > 100: break
    return list(set(counts))

if __name__ == "__main__":
    print(count_matches())

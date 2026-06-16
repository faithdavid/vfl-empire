import json, sys, time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from websocket import create_connection as ws_connect

def get_first_tab():
    resp = urlopen("http://127.0.0.1:9222/json", timeout=5)
    tabs = json.loads(resp.read().decode())
    for t in tabs:
        if t.get("url","").startswith("https://www.msport.com") or t.get("title","").startswith("MSport"):
            return t["webSocketDebuggerUrl"]
    return None

def ws_send(ws, method, params=None):
    msg = {"id": 1, "method": method, "params": params or {}}
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == 1:
            return resp.get("result", {})

def dump_elements():
    ws_url = get_first_tab()
    if not ws_url: return "No tab"
    ws = ws_connect(ws_url, timeout=10)
    
    js = """
    (() => {
        const elements = document.querySelectorAll('div, span, a, button, p, h1, h2, h3');
        const results = [];
        elements.forEach(el => {
            const text = el.innerText.trim();
            if (text && text.length < 50) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    results.append({text, x: r.x, y: r.y, w: r.width, h: r.height, tag: el.tagName});
                }
            }
        });
        return results;
    })()
    """
    # Fix results.append to results.push
    js = js.replace(".append(", ".push(")
    
    res = ws_send(ws, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True
    })
    ws.close()
    return res.get("result", {}).get("value", [])

if __name__ == "__main__":
    elements = dump_elements()
    print(json.dumps(elements, indent=2))

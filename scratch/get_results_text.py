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

def get_results_text():
    ws_url = get_first_tab()
    if not ws_url: return "No tab"
    ws = ws_connect(ws_url, timeout=10)
    
    # Try to find the results modal or section
    # MSport virtual results are often in a div with class 'm-virtual-results' or similar
    js = """
    (() => {
        const results = document.querySelector('.m-virtual-results');
        if (results) return results.innerText;
        const matches = document.querySelectorAll('.m-virtual-match-row');
        let text = "";
        matches.forEach(m => text += m.innerText + "\\n");
        return text || "No results found on page";
    })()
    """
    res = ws_send(ws, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True
    })
    ws.close()
    return res.get("result", {}).get("value", "")

if __name__ == "__main__":
    print(get_results_text())

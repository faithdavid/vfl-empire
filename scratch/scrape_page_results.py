import json, time, sys
from websocket import create_connection as ws_connect
from urllib.request import urlopen

def get_page_results():
    try:
        resp = urlopen("http://127.0.0.1:9222/json", timeout=5)
        tabs = json.loads(resp.read().decode())
        ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if "msport.com" in t.get("url",""))
        ws = ws_connect(ws_url, timeout=10)
        
        msg_id = 0
        def ws_send(method, params=None):
            nonlocal msg_id
            msg_id += 1
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == msg_id: return r
        
        ws_send("Runtime.enable")
        
        # Click Match Results tab
        expr = 'Array.from(document.querySelectorAll(".m-tabs-item")).find(t => t.innerText.includes("Match Results"))?.click()'
        ws_send("Runtime.evaluate", {"expression": expr})
        time.sleep(5) # Wait for results to load
        
        # Check if we are on the results tab and find the results
        expr = """
        (() => {
            const table = document.querySelector('.m-table');
            if (!table) return "TABLE_NOT_FOUND";
            return table.innerText;
        })()
        """
        res = ws_send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return res["result"].get("value", "NO_VALUE")
    except Exception as e:
        return str(e)

if __name__ == "__main__":
    print(get_page_results())

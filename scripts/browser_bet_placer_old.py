#!/usr/bin/env python3
"""
browser_bet_placer.py — Places VFL bets on MSport via Chrome DevTools Protocol.
Connects to local Chromium (port 9222), logs in, navigates, places bets.
"""

import json, sys, time, re, os, logging, traceback
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from websocket import create_connection as ws_connect

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('browser_bet_placer')

CHROME_WS = None
TAB_ID = None

def get_first_tab():
    resp = urlopen("http://127.0.0.1:9222/json", timeout=5)
    tabs = json.loads(resp.read().decode())
    for t in tabs:
        if t.get("url","").startswith("https://www.msport.com") or t.get("title","").startswith("MSport"):
            return t["webSocketDebuggerUrl"]
    # Create new tab — CDP requires PUT, not GET
    req = Request("http://127.0.0.1:9222/json/new?" + urlencode({"url":"about:blank"}), method="PUT")
    resp = urlopen(req, timeout=5)
    tab = json.loads(resp.read().decode())
    return tab["webSocketDebuggerUrl"]

def ws_send(method, params=None):
    global CHROME_WS, msg_id
    if CHROME_WS is None:
        ws_url = get_first_tab()
        CHROME_WS = ws_connect(ws_url, timeout=10)
        msg_id = 0
    msg_id += 1
    req = {"id": msg_id, "method": method, "params": params or {}}
    CHROME_WS.send(json.dumps(req))
    while True:
        resp = json.loads(CHROME_WS.recv())
        if resp.get("id") == msg_id:
            if "error" in resp:
                raise Exception(f"CDP error: {resp['error']}")
            return resp.get("result", {})

def ws_eval(js):
    result = ws_send("Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": True
    })
    val = result.get("result", {}).get("value")
    return val

def ws_click(selector, timeout_s=15):
    """Click an element by selector using proper pointer events."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        # Check if element exists
        exists = ws_eval(f"document.querySelector(`{selector}`) !== null")
        if exists:
            break
        time.sleep(0.5)
    if not exists:
        raise Exception(f"Element not found: {selector}")

    # Get bounding box
    box = ws_eval(f"""
        (() => {{
            const el = document.querySelector(`{selector}`);
            const r = el.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }})()
    """)
    x, y = box["x"], box["y"]

    # Dispatch proper pointer events (MSport requires this)
    for _ in range(2):  # Double click is sometimes needed
        ws_send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left",
            "clickCount": 1, "buttons": 1
        })
        ws_send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left",
            "clickCount": 1
        })
    return box

def parse_market_line(market):
    """Extract the O/U line from market string like 'Over 1.5 Goals' → 1.5, 'Under 2.5' → 2.5.
    Returns None if no line found (use default 2.5)."""
    import re
    m = re.search(r'(\d+\.\d+)', market)
    return m.group(1) if m else None


def select_specifier_line(home, away, target_line, target_md=None):
    """Change the Over/Under line specifier from default (2.5) to target_line (e.g. '1.5', '3.5').
    Operates on the fixture row matching home/away, scoped to target_md if provided.
    Returns True if line was set, False if already on correct line or failed."""
    target_md_js = f"'{target_md}'" if target_md else "null"
    # Check current line first
    current_line = ws_eval(f"""
        (() => {{
            let root = document;
            let target_md = {target_md_js};
            if (target_md) {{
                const containers = Array.from(document.querySelectorAll('.match-day'));
                const targetContainer = containers.find(c => {{
                    const bar = c.querySelector('.match-day-bar');
                    return bar && bar.innerText.includes('Match Day ' + target_md);
                }});
                if (targetContainer) root = targetContainer;
            }}
            let events = root.querySelectorAll('.virtual-event');
            for (let ev of events) {{
                let teams = ev.querySelector('.m-teams');
                if (!teams) continue;
                let txt = teams.innerText.toLowerCase();
                if (txt.includes('{home.lower()}') && txt.includes('{away.lower()}')) {{
                    let lineEl = ev.querySelector('.m-specifier-select .m-text');
                    return lineEl ? lineEl.innerText.trim() : null;
                }}
            }}
            return null;
        }})()
    """)
    if current_line == target_line:
        log.info(f"Already on line {target_line}, no need to change")
        return True
    if current_line is None:
        log.warning(f"Could not find current line for {home} vs {away}")
        return False

    log.info(f"Changing specifier from {current_line} → {target_line} for {home} vs {away}")

    # Click specifier dropdown to open options
    opened = ws_eval(f"""
        (() => {{
            let root = document;
            let target_md = {target_md_js};
            if (target_md) {{
                const containers = Array.from(document.querySelectorAll('.match-day'));
                const targetContainer = containers.find(c => {{
                    const bar = c.querySelector('.match-day-bar');
                    return bar && bar.innerText.includes('Match Day ' + target_md);
                }});
                if (targetContainer) root = targetContainer;
            }}
            let events = root.querySelectorAll('.virtual-event');
            for (let ev of events) {{
                let teams = ev.querySelector('.m-teams');
                if (!teams) continue;
                let txt = teams.innerText.toLowerCase();
                if (txt.includes('{home.lower()}') && txt.includes('{away.lower()}')) {{
                    let spec = ev.querySelector('.m-specifier-select .m-value');
                    if (spec) {{ spec.click(); return true; }}
                }}
            }}
            return false;
        }})()
    """)
    if not opened:
        log.warning("Failed to open specifier dropdown")
        return False
    time.sleep(0.5)

    # Click the target line option
    selected = ws_eval(f"""
        (() => {{
            let opts = document.querySelectorAll('.v-select-option');
            for (let opt of opts) {{
                if (opt.innerText.trim() === '{target_line}') {{
                    opt.click();
                    return true;
                }}
            }}
            return false;
        }})()
    """)
    time.sleep(0.8)  # Wait for odds to refresh
    if not selected:
        log.warning(f"Line {target_line} not found in specifier dropdown")
        return False

    log.info(f"Specifier set to {target_line}")
    return True


def ws_type_text(selector, text, timeout_s=15):
    """Type text into an input field. Handles Vue.js reactivity properly."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        exists = ws_eval(f"document.querySelector(`{selector}`) !== null")
        if exists:
            break
        time.sleep(0.5)
    if not exists:
        raise Exception(f"Input not found: {selector}")
    
    # Vue.js-safe value setter: uses native prototype setter to bypass Vue's
    # getter/setter proxy, then dispatches native input event Vue watches.
    ws_eval(f"""
        (() => {{
            const el = document.querySelector(`{selector}`);
            el.focus();
            const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
            if (proto && proto.set) {{
                proto.set.call(el, `{text}`);
            }} else {{
                el.value = `{text}`;
            }}
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})()
    """)

def login():
    """Log in to MSport if not already logged in."""
    url = "https://www.msport.com/ng/web/virtual"
    ws_send("Page.navigate", {"url": url})
    time.sleep(5)
    # Check if login form is visible
    log.info("Checking login state...")
    page_text = ws_eval("document.body.innerText.substring(0, 200)")
    if "Login" not in page_text and "Welcome" not in page_text:
        log.info("Already logged in (no login form)")
        return True
    if "Welcome" in page_text:
        log.info("Already logged in")
        return True

    log.info("Login form detected, logging in...")
    # Find and fill phone input
    ws_type_text("input[placeholder*='Mobile']", "09038426877")
    # Find and fill password
    ws_type_text("input[type='password']", "fadava2002")
    time.sleep(1)
    # Click login button — find by inner text
    ws_eval("""Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Login')?.click()""")
    time.sleep(5)
    # Verify login success
    page_text = ws_eval("document.body.innerText.substring(0, 500)")
    if "Login" in page_text and "Welcome" not in page_text:
        log.warning("Login might have failed")
        return False
    log.info("Login successful")
    return True

def get_balance():
    """Get current account balance."""
    bal = ws_eval("""
        (() => {
            let el = document.querySelector('[class*="balance"]');
            if (!el) el = document.querySelector('[class*="Balance"]');
            if (!el) el = document.querySelector('.header-balance, .wallet-balance, [class*="wallet"]');
            return el ? el.innerText : null;
        })()
    """)
    return bal

def place_bet(fixture_home, fixture_away, market, odds, stake, target_md=None):
    """Place a single bet on a fixture."""
    log.info(f"Placing bet: {fixture_home} vs {fixture_away} -> {market} @{odds} (stake: ₦{stake}) on MD{target_md}")

    # Login/Navigate to VFL page
    url = "https://www.msport.com/ng/web/virtual"
    ws_send("Page.navigate", {"url": url})
    time.sleep(7)

    # Ensure correct matchday tab is selected
    if target_md:
        select_matchday_tab(target_md)

    # Close any popup overlay
    ws_eval("document.querySelector('.ui-dialog--wrap')?.remove()")
    time.sleep(1)

    # Check we're on the right page
    title = ws_eval("document.title")
    log.info(f"Page title: {title}")

    # Clear any old bets in betslip before starting
    ws_eval("Array.from(document.querySelectorAll('a, span')).find(el => el.innerText.includes('Remove all'))?.click()")
    time.sleep(1)

    # Find fixture by scanning the virtual-event elements
    log.info("Searching for fixture in virtual-event list...")
    fixture_data = ws_eval(f"""
        (() => {{
            let events = document.querySelectorAll('.virtual-event');
            for (let ev of events) {{
                let teams = ev.querySelector('.m-teams');
                if (!teams) continue;
                let txt = teams.innerText.toLowerCase();
                if (txt.includes('{fixture_home.lower()}') && txt.includes('{fixture_away.lower()}')) {{
                    ev.scrollIntoView({{behavior:'instant', block:'center'}});
                    return 'found';
                }}
            }}
            return 'not_found';
        }})()
    """)
    log.info(f"Fixture search: {fixture_data}")

    if fixture_data != 'found':
        log.warning("Fixture not found, trying broader search...")
        fixture_data = ws_eval(f"""
            (() => {{
                let all = document.querySelectorAll('[class*=\"event\"]');
                for (let ev of all) {{
                    let txt = ev.innerText.toLowerCase();
                    if (txt.includes('{fixture_home.lower()}') && txt.includes('{fixture_away.lower()}')) {{
                        ev.scrollIntoView({{behavior:'instant', block:'center'}});
                        return 'found_broad';
                    }}
                }}
                return 'not_found';
            }})()
        """)
        log.info(f"Broad fixture search: {fixture_data}")

    if 'not_found' in str(fixture_data):
        raise Exception(f"Fixture not found: {fixture_home} vs {fixture_away}")

    time.sleep(2)

    # ── Select the correct O/U line (1.5, 2.5, 3.5) via the specifier dropdown ──
    target_line = parse_market_line(market)
    if target_line and target_line != "2.5":
        log.info(f"Selecting O/U line {target_line} for {fixture_home} vs {fixture_away}...")
        line_set = select_specifier_line(fixture_home, fixture_away, target_line, target_md=target_md)
        if not line_set:
            raise Exception(f"Failed to set O/U line to {target_line} for {fixture_home} vs {fixture_away}")

    is_over = "Over" in market
    is_under = "Under" in market
    is_cs = market.startswith("CS")
    is_dc = market in ["1 X", "1 2", "X 2"]
    is_1x2 = market in ["1", "X", "2"]
    
    if is_cs or is_dc:
        target_desc = market.split(" ")[1] if is_cs else market
        log.info(f"Navigating to deep markets for {market}...")
        ws_eval(f"""
            (() => {{
                let events = document.querySelectorAll('.virtual-event');
                for (let ev of events) {{
                    let teams = ev.querySelector('.m-teams');
                    if (teams && teams.innerText.toLowerCase().includes('{fixture_home.lower()}') && teams.innerText.toLowerCase().includes('{fixture_away.lower()}')) {{
                        let moreBtn = Array.from(ev.querySelectorAll('div, a, span')).find(el => el.innerText && el.innerText.trim().startsWith('+'));
                        if (moreBtn) moreBtn.click();
                        return;
                    }}
                }}
            }})()
        """)
        time.sleep(2)

    log.info(f"Finding odds for {market} @{odds}...")
    target_md_js = f"'{target_md}'" if target_md else "null"
    js_market_type = "'deep'" if (is_cs or is_dc) else ("'1x2'" if is_1x2 else "'ou'")
    js_selection = f"'{market}'"
    js_desc = f"'{market.split(' ')[1]}'" if is_cs else (f"'{market}'" if is_dc else "null")
    
    coords = ws_eval(f"""
        (() => {{
            let root = document;
            let target_md = {target_md_js};
            if (target_md) {{
                const containers = Array.from(document.querySelectorAll('.match-day'));
                const targetContainer = containers.find(c => {{
                    const bar = c.querySelector('.match-day-bar');
                    return bar && bar.innerText.includes('Match Day ' + target_md);
                }});
                if (targetContainer) root = targetContainer;
            }}
            
            if ({js_market_type} === 'deep') {{
                let items = Array.from(root.querySelectorAll('.virtual-outcome, .m-outcome'));
                let target = items.find(el => {{
                    let desc = el.querySelector('.desc')?.innerText || '';
                    return desc.trim() === {js_desc};
                }});
                if (target) {{
                    let r = target.getBoundingClientRect();
                    return {{ x: r.x + r.width/2, y: r.y + r.height/2 }};
                }}
                return null;
            }}
            
            let events = root.querySelectorAll('.virtual-event');
            for (let ev of events) {{
                let teams = ev.querySelector('.m-teams');
                if (!teams) continue;
                let txt = teams.innerText.toLowerCase();
                if (txt.includes('{fixture_home.lower()}') && txt.includes('{fixture_away.lower()}')) {{
                    if ({js_market_type} === '1x2') {{
                        let oddsEls = Array.from(ev.querySelectorAll('a.virtual-outcome'));
                        let idx = -1;
                        if ({js_selection} === '1') idx = 0;
                        else if ({js_selection} === 'X') idx = 1;
                        else if ({js_selection} === '2') idx = 2;
                        if (idx >= 0 && oddsEls.length > idx) {{
                            let r = oddsEls[idx].getBoundingClientRect();
                            return {{ x: r.x + r.width/2, y: r.y + r.height/2 }};
                        }}
                    }} else {{
                        let secondMarket = ev.querySelector('.second-market');
                        if (!secondMarket) return null;
                        let oddsEls = secondMarket.querySelectorAll('a.virtual-outcome');
                        let col = ({js_selection}.includes('Over')) ? 0 : 1;
                        if (oddsEls.length > col) {{
                            let r = oddsEls[col].getBoundingClientRect();
                            return {{ x: r.x + r.width/2, y: r.y + r.height/2 }};
                        }}
                    }}
                }}
            }}
            return null;
        }})()
    """)
    
    if isinstance(coords, dict) and 'x' in coords:
        log.info(f"  Clicking odds for {fixture_home} vs {fixture_away} at {coords['x']},{coords['y']}...")
        ws_send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": coords['x'], "y": coords['y'], 
            "button": "left", "clickCount": 1, "buttons": 1
        })
        ws_send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": coords['x'], "y": coords['y'], 
            "button": "left", "clickCount": 1
        })
        time.sleep(1)
        
        # Enter stake in betslip
        log.info("Entering stake...")
        ws_type_text("aside .bet-input input", f"{stake:.2f}")
        time.sleep(1)

    # Get initial balance first
    initial_bal_str = ws_eval("(document.querySelector('[class*=\"balance\"]') || document.querySelector('[class*=\"Balance\"]'))?.innerText?.trim() || ''")

    # Click Place Bet
    log.info("Clicking Place Bet...")
    ws_eval("Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Place Bet') && !b.innerText.includes('Add More'))?.click()")
    time.sleep(3)

    # Handle confirmation dialog
    log.info("Handling confirmation...")
    confirmed = ws_eval("Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Confirm Bet')?.click()")
    time.sleep(2)

    # Get result
    page_text = ws_eval("document.body.innerText.substring(0, 1000)")
    # Get final balance
    final_bal_str = ws_eval("(document.querySelector('[class*=\"balance\"]') || document.querySelector('[class*=\"Balance\"]'))?.innerText?.trim() || ''")
    
    # Clean balances for comparison
    def clean_bal(s):
        try:
            return float(s.replace("NGN", "").replace(",", "").strip())
        except: return None
        
    b1 = clean_bal(initial_bal_str)
    b2 = clean_bal(final_bal_str)

    success = ("success" in page_text.lower() or "placed" in page_text.lower()
               or "congratulations" in page_text.lower()
               or "bet placed" in page_text.lower()
               or "bet has been placed" in page_text.lower()
               or "accepted" in page_text.lower())
    
    if not success and b1 is not None and b2 is not None:
        deduction = b1 - b2
        if deduction >= float(stake) - 0.01:
            log.info(f"✅ Success confirmed via balance deduction: {b1} -> {b2} (stake: {stake})")
            success = True
    if success:
        log.info("✅ Bet placed successfully!")
    else:
        log.warning("❌ Bet placement failed or outcome unclear")
        log.info(f"Page text: {page_text[:500]}")

    return {
        "success": success,
        "error": "Outcome unclear or keywords not found" if not success else None,
        "fixture": f"{fixture_home} vs {fixture_away}",
        "market": market, "odds": float(odds), "stake": float(stake),
        "page_text": page_text[:500]
    }


def select_matchday_tab(target_md):
    """Ensure the target matchday section is visible/scrolled to and clicked."""
    if not target_md: return False
    log.info(f"Ensuring matchday section for MD{target_md} is visible and active...")
    
    # MSport Virtuals sometimes take a moment to render the next MD tab
    for attempt in range(3):
        js = f"""
            (() => {{
                // MSport virtual EPL matchday tabs are usually .m-tabs-item or have text Match Day X
                const items = Array.from(document.querySelectorAll('.m-tabs-item, .match-day-bar, .match-day'));
                const target = items.find(t => t.innerText.includes('{target_md}'));
                if (target) {{
                    target.click();
                    target.scrollIntoView({{behavior:'instant', block:'center'}});
                    return true;
                }}
                return false;
            }})()
        """
        success = ws_eval(js)
        if success:
            log.info(f"✅ Selected MD{target_md} tab.")
            time.sleep(2) # Essential wait for odds to load
            return True
        log.info(f"  Attempt {attempt+1}: MD{target_md} tab not found yet, waiting...")
        time.sleep(3)

    log.warning(f"❌ Failed to select MD{target_md} tab after 3 attempts.")
    return False

def place_parlay(legs, stake, target_md=None):
    """Place a multi-leg parlay. Clicks each leg's odds, then submits slip."""
    log.info(f"Placing {len(legs)}-leg parlay (stake: ₦{stake}) on MD{target_md}")

    # Login/Navigate to VFL page
    url = "https://www.msport.com/ng/web/virtual"
    ws_send("Page.navigate", {"url": url})
    time.sleep(7)

    # Ensure correct matchday tab is selected
    if target_md:
        select_matchday_tab(target_md)
    time.sleep(1)
    title = ws_eval("document.title")
    log.info(f"Page title: {title}")

    # Clear any old bets in betslip before starting
    ws_eval("Array.from(document.querySelectorAll('a, span')).find(el => el.innerText.includes('Remove all'))?.click()")
    time.sleep(1)

    for i, leg in enumerate(legs, 1):
        home = leg["home"]
        away = leg["away"]
        market = leg.get("market", leg.get("selection", ""))
        is_over = "Over" in market
        is_under = "Under" in market
        is_dc = market in ["1 X", "1 2", "X 2"]
        is_1x2 = market in ["1", "X", "2"]
        
        if is_dc:
            target_desc = market
            log.info(f"Navigating to deep markets for {market}...")
            ws_eval(f"""
                (() => {{
                    let events = document.querySelectorAll('.virtual-event');
                    for (let ev of events) {{
                        let teams = ev.querySelector('.m-teams');
                        if (!teams) continue;
                        let txt = teams.innerText.toLowerCase();
                        if (txt.includes('{home.lower()}') && txt.includes('{away.lower()}')) {{
                            let moreBtn = Array.from(ev.querySelectorAll('div, a, span')).find(el => el.innerText && el.innerText.trim().startsWith('+'));
                            if (moreBtn) moreBtn.click();
                            return;
                        }}
                    }}
                }})()
            """)
            time.sleep(2)
        
        market_col = 0
        if is_over: market_col = 0
        elif is_under: market_col = 1
        
        log.info(f"Leg {i}/{len(legs)}: {home} vs {away} → {market}")

        if not is_1x2:
            # ── Select the correct O/U line via specifier dropdown ──
            target_line = parse_market_line(market)
            if target_line and target_line != "2.5":
                log.info(f"Selecting O/U line {target_line} for {home} vs {away}...")
                select_specifier_line(home, away, target_line, target_md=target_md)

        # Click odds
        target_md_js = f"'{target_md}'" if target_md else "null"
        js_market_type = "'deep'" if is_dc else ("'1x2'" if is_1x2 else "'ou'")
        js_selection = f"'{market}'"
        js_desc = f"'{market}'" if is_dc else "null"
        
        result = ws_eval(f"""
            (() => {{
                let root = document;
                let target_md = {target_md_js};
                if (target_md) {{
                    const containers = Array.from(document.querySelectorAll('.match-day'));
                    const targetContainer = containers.find(c => {{
                        const bar = c.querySelector('.match-day-bar');
                        return bar && bar.innerText.includes('Match Day ' + target_md);
                    }});
                    if (targetContainer) root = targetContainer;
                }}
                if ({js_market_type} === 'deep') {{
                    let items = Array.from(root.querySelectorAll('.virtual-outcome, .m-outcome'));
                    let target = items.find(el => {{
                        let desc = el.querySelector('.desc')?.innerText || '';
                        return desc.trim() === {js_desc};
                    }});
                    if (target) {{
                        target.click();
                        return 'clicked';
                    }}
                    return 'deep_selection_failed';
                }}
                
                let events = root.querySelectorAll('.virtual-event');
                for (let ev of events) {{
                    let teams = ev.querySelector('.m-teams');
                    if (!teams) continue;
                    let txt = teams.innerText.toLowerCase();
                    if (txt.includes('{home.lower()}') && txt.includes('{away.lower()}')) {{
                        if ({js_market_type} === '1x2') {{
                            let oddsEls = Array.from(ev.querySelectorAll('a.virtual-outcome'));
                            let idx = -1;
                            if ({js_selection} === '1') idx = 0;
                            else if ({js_selection} === 'X') idx = 1;
                            else if ({js_selection} === '2') idx = 2;
                            
                            if (idx >= 0 && oddsEls.length > idx) {{
                                oddsEls[idx].click();
                                return 'clicked';
                            }}
                            return '1x2_selection_failed';
                        }} else {{
                            let secondMarket = ev.querySelector('.second-market');
                            if (!secondMarket) return 'no_second_market';
                            let oddsEls = secondMarket.querySelectorAll('a.virtual-outcome');
                            let col = {market_col};
                            if (oddsEls.length > col) {{
                                oddsEls[col].click();
                                return 'clicked';
                            }}
                            return 'ou_odds_not_found';
                        }}
                    }}
                }}
                return 'fixture_not_found';
            }})()
        """)
        
        if result == 'clicked':
            log.info(f"  Leg {i} successfully clicked and selected directly.")
            time.sleep(1.0)
        else:
            log.warning(f"  Leg {i} FAILED: {home} vs {away} (Result: {result})")

    # ── Enter stake in betslip ──
    log.info("Entering stake...")
    is_multi = len(legs) > 1
    
    # Ensure correct tab is selected (Multiple for 2+ legs, Single for 1)
    if is_multi:
        ws_eval("Array.from(document.querySelectorAll('.m-bet-slip-tabs .tab')).find(t => t.innerText.includes('Multiple'))?.click()")
    else:
        ws_eval("Array.from(document.querySelectorAll('.m-bet-slip-tabs .tab')).find(t => t.innerText.includes('Single'))?.click()")
    time.sleep(1)

    # Try multiple selectors for the stake input
    input_found = ws_eval(f"""
        (() => {{
            const multiSelectors = [
                ".m-virtual-multiple-stake-input input",
                "aside .m-virtual-mutiple-edit .bet-input input",
                ".m-bet-slip-multiple input",
                ".m-virtual-multiple-input input",
                "input[placeholder*='Multiple']"
            ];
            const singleSelectors = [
                "aside .bet-input input",
                ".betslip-input input",
                ".m-bet-slip-single input",
                ".m-virtual-single-input input",
                "input[placeholder*='Stake']"
            ];
            const generalSelectors = [
                "aside .m-input",
                "aside input[type='number']",
                "aside input",
                ".m-bet-slip input"
            ];
            
            let selectors = {{ 'true': multiSelectors, 'false': singleSelectors }}['{str(is_multi).lower()}'].concat(generalSelectors);
            
            for (let s of selectors) {{
                let el = document.querySelector(s);
                if (el && el.offsetParent !== null) {{ // Visible
                    return s;
                }}
            }}
            
            // Final fallback: any visible input in the aside
            let aside = document.querySelector('aside');
            if (aside) {{
                let inputs = Array.from(aside.querySelectorAll('input'));
                let visible = inputs.find(i => i.offsetParent !== null);
                if (visible) return 'aside input';
            }}
            
            return null;
        }})()
    """)
    
    if not input_found:
        # One last ditch effort: just find ANY input that is visible in the whole sidebar
        input_found = ws_eval("(() => { let i = Array.from(document.querySelectorAll('aside input')).find(el => el.offsetParent !== null); return i ? 'aside input' : null; })()")

    if not input_found:
        aside_text = ws_eval('document.querySelector("aside")?.innerText.substring(0, 500)')
        raise Exception(f"Input not found: could not locate stake input in {'multiple' if is_multi else 'single'} betslip. Page content snippet: {aside_text}")

    log.info(f"Using input selector: {input_found}")
    ws_type_text(input_found, str(stake))
    time.sleep(1)

    # ── Click Place Bet ──
    # Get initial balance first
    initial_bal_str = ws_eval("(document.querySelector('[class*=\"balance\"]') || document.querySelector('[class*=\"Balance\"]'))?.innerText?.trim() || ''")

    log.info("Clicking Place Bet...")
    ws_eval("""
        (() => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Place Bet') && !b.innerText.includes('Add More'));
            if (btn) {
                btn.scrollIntoView({behavior:'instant', block:'center'});
                btn.click();
                // Backup dispatch if click is intercepted
                btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                return true;
            }
            return false;
        })()
    """)
    time.sleep(3)

    # ── Handle confirmation ──
    log.info("Confirming bet...")
    # MSport often pops a modal for confirmation
    confirmed = ws_eval("""
        (() => {
            const confirmBtn = Array.from(document.querySelectorAll('button, .ui-dialog-btn')).find(b => 
                b.innerText.trim() === 'Confirm Bet' || b.innerText.includes('Confirm')
            );
            if (confirmBtn) {
                confirmBtn.click();
                return true;
            }
            return false;
        })()
    """)
    if not confirmed:
        log.info("  No confirmation button found, checking if bet was already placed...")
    else:
        log.info("  ✅ Clicked Confirm.")
    time.sleep(5)

    # ── Check for success toast/banner immediately ──
    pg = ws_eval("document.body.innerText.substring(0, 1500)")
    
    # Get final balance
    final_bal_str = ws_eval("(document.querySelector('[class*=\"balance\"]') || document.querySelector('[class*=\"Balance\"]'))?.innerText?.trim() || ''")
    
    # Clean balances for comparison
    def clean_bal(s):
        try:
            return float(s.replace("NGN", "").replace(",", "").strip())
        except: return None
        
    b1 = clean_bal(initial_bal_str)
    b2 = clean_bal(final_bal_str)

    # Success signals: positive keywords OR balance deduction matching stake
    success_kw = ("success" in pg.lower() or "placed" in pg.lower()
                  or "congratulations" in pg.lower() or "bet placed" in pg.lower()
                  or "accepted" in pg.lower() or "bet has been placed" in pg.lower())

    success = success_kw
    if not success and b1 is not None and b2 is not None:
        deduction = b1 - b2
        if deduction >= float(stake) - 0.01: # allow for small float diff
            log.info(f"✅ Success confirmed via balance deduction: {b1} -> {b2} (stake: {stake})")
            success = True

    if success:
        log.info("✅ Bet placed successfully!")
        ws_eval("document.querySelector('.ui-dialog--wrap .close, .ui-dialog-btn-close')?.click()")
    else:
        log.warning("❌ Bet placement failed or outcome unclear")
    
    return {
        "success": success,
        "leg_count": len(legs),
        "stake": float(stake),
        "balance": final_bal_str or "unknown",
        "page_text": pg[:300]
    }


def get_betting_matchdays():
    """Extract list of matchdays available for betting on the page, filtering out those with < 40 seconds left."""
    data = ws_eval(r"""
        (() => {
            let season = "";
            let bodyText = document.body.innerText;
            let seasonMatch = bodyText.match(/(\d+)\s*\/\s*Match\s*Day/i);
            if (seasonMatch) {
                season = "VFLM " + seasonMatch[1];
            } else {
                let seasonEl = document.querySelector('.m-season-name, .season-name, .match-day-title');
                if (seasonEl) season = seasonEl.innerText.trim();
            }
            
            let elements = document.querySelectorAll('.match-day-bar');
            let mds = Array.from(elements).map(el => {
                let txt = el.innerText || '';
                let m = txt.match(/Match Day\s+(\d+)/i);
                if (!m) return null;
                let md = parseInt(m[1]);
                let countdown = 999;
                let timeParts = txt.match(/(\d+):(\d+)/);
                if (timeParts) {
                    let mins = parseInt(timeParts[1]);
                    let secs = parseInt(timeParts[2]);
                    countdown = mins * 60 + secs;
                }
                return { "matchday": md, "countdown": countdown };
            }).filter(x => x !== null);
            
            return { "season": season, "mds": mds };
        })()
    """)
    if not data:
        return []
    
    season = data.get("season", "")
    md_list = data.get("mds", [])
    
    result = []
    for item in md_list:
        md = item["matchday"]
        seconds = item["countdown"]
        if seconds < 40:
            log.warning(f"Skipping MD{md} because countdown is too low ({seconds}s left)")
            continue
        result.append(md)
        
    return sorted(list(set(result))), season


if __name__ == "__main__":
    # Simple CLI for testing or orchestration
    import argparse, traceback
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["bet", "parlay", "balance", "history"], help="Mode: bet, parlay, balance or history")
    parser.add_argument("data", nargs="?", help="JSON data for placement")
    parser.add_argument("--stake", type=float, help="Stake for single bet")
    args = parser.parse_args()

    try:
        ws_send("Page.enable")
        ws_send("Runtime.enable")
        log.info("Connected to Chromium CDP")
        login()
        
        if args.mode == "history":
            # Find and click "Bet History" by text
            box = ws_eval("""
                (() => {
                    const elements = document.querySelectorAll('div, span, a, button');
                    for (const el of elements) {
                        if (el.innerText === 'Bet History') {
                            const r = el.getBoundingClientRect();
                            return {x: r.x + r.width/2, y: r.y + r.height/2};
                        }
                    }
                    return null;
                })()
            """)
            if box:
                x, y = box["x"], box["y"]
                ws_send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1})
                ws_send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
                time.sleep(2)
                history = ws_eval("document.body.innerText")
                print(json.dumps({"success": True, "history": history}))
            else:
                print(json.dumps({"success": False, "error": "Bet History button not found"}))
            sys.exit(0)

        if args.mode == "balance":
            mds, season = get_betting_matchdays()
            bal = get_balance()
            print(json.dumps({"success": True, "balance": bal, "matchday": mds[0] if mds else None, "available_mds": mds, "season": season}))
            sys.exit(0)

        # For bet/parlay, we need data
        if not args.data and sys.stdin.isatty():
            print(json.dumps({"success": False, "error": "No data provided"}))
            sys.exit(1)
            
        if not args.data:
            data = json.load(sys.stdin)
        else:
            data = json.loads(args.data)

        if args.mode == "parlay":
            legs = data.get("legs", [])
            stake = data.get("stake", 50)
            target_md = data.get("matchday")
            result = place_parlay(legs, stake, target_md=target_md)
            print(json.dumps(result, indent=2))
        else:
            # Single bet
            if isinstance(data, list):
                fixture = data[0]
            else:
                fixture = data
            
            home = fixture.get("home", "")
            away = fixture.get("away", "")
            market = fixture.get("market", fixture.get("selection", ""))
            odds = fixture.get("odds", 0)
            stake = args.stake or fixture.get("stake", 50)
            target_md = data.get("matchday") or fixture.get("matchday")
            
            result = place_bet(home, away, market, odds, stake, target_md=target_md)
            print(json.dumps(result, indent=2))

    except Exception as e:
        log.error(f"Error: {e}")
        print(json.dumps({"success": False, "error": str(e)}))
    finally:
        if CHROME_WS:
            CHROME_WS.close()

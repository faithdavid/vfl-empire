import json
import pandas as pd

def generate_table_html(data_file, table_id, is_micro=False):
    with open(data_file, 'r') as f:
        data = json.load(f)
        
    df = pd.DataFrame(data)
    df = df[df['occurrences'] >= 10]
    df = df.sort_values(by=['occurrences'], ascending=False)
    
    html = f"""
    <table id="{table_id}">
        <thead>
            <tr>
                <th>Home Team</th>
                <th>Away Team</th>
                <th>Home Tier</th>
                <th>Away Tier</th>
                <th>Occurrences</th>
                <th>Avg Goals</th>
                <th>1 Rate</th>
                <th>X Rate</th>
                <th>2 Rate</th>
                <th>U1.5 Rate</th>
                <th>O1.5 Rate</th>
                <th>U2.5 Rate</th>
                <th>U3.5 Rate</th>
                <th>O2.5 Rate</th>
                <th>O3.5 Rate</th>
                <th>GG Rate</th>
            </tr>
        </thead>
        <tbody>
"""

    def format_tier(t):
        t_class = t.lower()
        if is_micro:
            t_class = "micro-" + t_class # Avoid css conflicts if needed
            return f'<span class="highlight">{t}</span>'
        else:
            return f'<span class="{t_class}">{t}</span>'

    for _, row in df.iterrows():
        hw = f"{row['w_1_rate']*100:.1f}%"
        dr = f"{row['w_x_rate']*100:.1f}%"
        aw = f"{row['w_2_rate']*100:.1f}%"
        u15 = f"{row['w_u15_rate']*100:.1f}%"
        o15 = f"{row['w_o15_rate']*100:.1f}%"
        u25 = f"{row['w_u25_rate']*100:.1f}%"
        u35 = f"{row['w_u35_rate']*100:.1f}%"
        o25 = f"{row['w_o25_rate']*100:.1f}%"
        o35 = f"{row['w_o35_rate']*100:.1f}%"
        gg = f"{row['w_gg_rate']*100:.1f}%"
        
        # Highlight strong signals
        u25_html = f'<span class="highlight">{u25}</span>' if row['w_u25_rate'] >= 0.9 else u25
        o25_html = f'<span class="highlight">{o25}</span>' if row['w_o25_rate'] >= 0.9 else o25
        u35_html = f'<span class="highlight">{u35}</span>' if row['w_u35_rate'] >= 0.95 else u35
        o35_html = f'<span class="highlight">{o35}</span>' if row['w_o35_rate'] >= 0.85 else o35
        o15_html = f'<span class="highlight">{o15}</span>' if row['w_o15_rate'] >= 0.95 else o15
        hw_html = f'<span class="highlight">{hw}</span>' if row['w_1_rate'] >= 0.85 else hw
        dr_html = f'<span class="highlight">{dr}</span>' if row['w_x_rate'] >= 0.85 else dr
        aw_html = f'<span class="highlight">{aw}</span>' if row['w_2_rate'] >= 0.85 else aw
        
        tier_h = row['home_tier']
        tier_a = row['away_tier']
        
        html += f"""
            <tr>
                <td>{row['home']}</td>
                <td>{row['away']}</td>
                <td>{format_tier(tier_h)}</td>
                <td>{format_tier(tier_a)}</td>
                <td>{row['occurrences']}</td>
                <td>{row['w_avg_goals']:.2f}</td>
                <td>{hw_html}</td>
                <td>{dr_html}</td>
                <td>{aw_html}</td>
                <td>{u15}</td>
                <td>{o15_html}</td>
                <td>{u25_html}</td>
                <td>{u35_html}</td>
                <td>{o25_html}</td>
                <td>{o35_html}</td>
                <td>{gg}</td>
            </tr>"""
            
    html += """
        </tbody>
    </table>
"""
    return html

def generate_html():
    macro_html = generate_table_html('/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json', 'macroTable', is_micro=False)
    micro_html = generate_table_html('/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json', 'microTable', is_micro=True)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VFL Full Data Coding & Standing Patterns</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; margin: 2rem; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; cursor: pointer; }}
        tr:hover {{ background: #334155; }}
        .t1 {{ color: #10b981; font-weight: bold; }}
        .t2 {{ color: #3b82f6; font-weight: bold; }}
        .t3 {{ color: #f59e0b; font-weight: bold; }}
        .t4 {{ color: #ef4444; font-weight: bold; }}
        .highlight {{ color: #10b981; font-weight: bold; }}
        .tabs {{ margin-bottom: 20px; }}
        .tab-btn {{ background: #334155; color: white; border: none; padding: 10px 20px; cursor: pointer; border-radius: 4px; font-size: 1rem; margin-right: 10px; }}
        .tab-btn.active {{ background: #38bdf8; font-weight: bold; }}
        .table-container {{ display: none; }}
        .table-container.active {{ display: block; }}
    </style>
</head>
<body>
    <h1>Full Database: Conditional Standing Pattern Locks</h1>
    <p style="font-size: 1.1rem; color: #cbd5e1;">This contains every fixture pattern extracted from history.db (minimum 10 occurrences) separated by league standing tiers.</p>
    
    <div style="background: #1e293b; padding: 1.5rem; border-radius: 8px; border-left: 4px solid #38bdf8; margin: 1.5rem 0;">
        <h3 style="margin-top: 0; color: #fff;">🔑 LEAGUE TIER KEY (Standings Map)</h3>
        <p style="margin-bottom: 0;">These patterns are conditioned on the teams' exact table positions at the time of the match:</p>
        <ul style="display: flex; gap: 20px; list-style-type: none; padding-left: 0; margin-top: 10px; flex-wrap: wrap;">
            <li style="background: #334155; padding: 10px 15px; border-radius: 6px;"><strong class="t1">Macro Tiers (T1-T4):</strong> Bins of 4 positions (e.g. 1st-4th)</li>
            <li style="background: #334155; padding: 10px 15px; border-radius: 6px;"><strong class="highlight">Micro Tiers (A-H):</strong> Bins of 2 positions (e.g. A=1st-2nd, B=3rd-4th)</li>
        </ul>
    </div>
    
    <div class="tabs">
        <button class="tab-btn active" onclick="showTab('macro')">Show Macro Tiers (T1 - T4)</button>
        <button class="tab-btn" onclick="showTab('micro')">Show Micro Tiers (A - H)</button>
    </div>
    
    <div id="macro-container" class="table-container active">
        {macro_html}
    </div>
    
    <div id="micro-container" class="table-container">
        {micro_html}
    </div>
    
    <script>
    function showTab(tabName) {{
        document.querySelectorAll('.table-container').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        
        document.getElementById(tabName + '-container').classList.add('active');
        event.target.classList.add('active');
    }}
    
    // Simple table sorting
    const getCellValue = (tr, idx) => tr.children[idx].innerText || tr.children[idx].textContent;
    const comparer = (idx, asc) => (a, b) => ((v1, v2) => 
        v1 !== '' && v2 !== '' && !isNaN(v1.replace('%','')) && !isNaN(v2.replace('%','')) ? v1.replace('%','') - v2.replace('%','') : v1.toString().localeCompare(v2)
        )(getCellValue(asc ? a : b, idx), getCellValue(asc ? b : a, idx));
    document.querySelectorAll('th').forEach(th => th.addEventListener('click', (() => {{
        const table = th.closest('table');
        Array.from(table.querySelectorAll('tbody tr'))
            .sort(comparer(Array.from(th.parentNode.children).indexOf(th), this.asc = !this.asc))
            .forEach(tr => table.querySelector('tbody').appendChild(tr) );
    }})));
    </script>
</body>
</html>
"""

    with open('/home/ubuntu/faith-workspace/vfl-empire/surge-findings/index.html', 'w') as f:
        f.write(html)

if __name__ == '__main__':
    generate_html()

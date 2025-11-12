import base64
import io
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def _to_png_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")

def build_dashboard(csv_path="ai_acceptance_metrics.csv", html_out="ai_acceptance_dashboard.html"):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    if "Date" not in df.columns:
        raise ValueError("CSV must contain a 'Date' column.")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce", utc=True)
    df = df.sort_values("Date").reset_index(drop=True)

    for col in ["SurvivalRate", "ImmediateReworkRate", "LinesAdded", "FilesTouched"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["SurvivalRate"] = df["SurvivalRate"].fillna(0.0)
    if "ImmediateReworkRate" in df.columns:
        df["ImmediateReworkRate"] = df["ImmediateReworkRate"].replace("", np.nan).astype(float)
    else:
        df["ImmediateReworkRate"] = np.nan

    df["AI_Quality_Index"] = df["SurvivalRate"] * (1 - df["ImmediateReworkRate"].fillna(0))

    # Rolling means (7-day) on a daily resample
    if df["Date"].notna().any():
        tmp = df.set_index("Date").sort_index()
        daily = tmp.resample("1D").mean(numeric_only=True)
        roll_sr = daily["SurvivalRate"].rolling(7, min_periods=1).mean()
        roll_ir = daily["ImmediateReworkRate"].rolling(7, min_periods=1).mean()
        roll_qi = daily["AI_Quality_Index"].rolling(7, min_periods=1).mean()
        x_roll = roll_sr.index
    else:
        roll_sr = roll_ir = roll_qi = None
        x_roll = None

    charts = {}

    # Survival over time
    fig1 = plt.figure()
    plt.plot(df["Date"], df["SurvivalRate"], marker="o", linestyle="-")
    if x_roll is not None:
        plt.plot(x_roll, roll_sr, linestyle="--")
    plt.title("Survival Rate over Time")
    plt.xlabel("Date")
    plt.ylabel("SurvivalRate (0–1)")
    plt.grid(True, alpha=0.3)
    charts["survival"] = _to_png_b64(fig1)

    # Immediate rework over time
    fig2 = plt.figure()
    plt.plot(df["Date"], df["ImmediateReworkRate"], marker="o", linestyle="-")
    if x_roll is not None:
        plt.plot(x_roll, roll_ir, linestyle="--")
    plt.title("Immediate Rework Rate over Time")
    plt.xlabel("Date")
    plt.ylabel("ImmediateReworkRate (0–1)")
    plt.grid(True, alpha=0.3)
    charts["immediate"] = _to_png_b64(fig2)

    # Scatter: LinesAdded vs SurvivalRate
    if "LinesAdded" in df.columns:
        fig3 = plt.figure()
        plt.scatter(df["LinesAdded"], df["SurvivalRate"])
        plt.title("Churn Correlation: LinesAdded vs SurvivalRate")
        plt.xlabel("LinesAdded per Commit")
        plt.ylabel("SurvivalRate (0–1)")
        plt.grid(True, alpha=0.3)
        charts["scatter"] = _to_png_b64(fig3)
    else:
        charts["scatter"] = ""

    # AI Quality Index over time
    fig4 = plt.figure()
    plt.plot(df["Date"], df["AI_Quality_Index"], marker="o", linestyle="-")
    if x_roll is not None:
        plt.plot(x_roll, roll_qi, linestyle="--")
    plt.title("AI Quality Index over Time")
    plt.xlabel("Date")
    plt.ylabel("AI_Quality_Index (0–1)")
    plt.grid(True, alpha=0.3)
    charts["qi"] = _to_png_b64(fig4)

    total_commits = len(df)
    total_lines = int(df["LinesAdded"].fillna(0).sum()) if "LinesAdded" in df.columns else 0
    overall_sr = float(df["SurvivalRate"].replace([np.inf, -np.inf], np.nan).mean())
    overall_ir = float(df["ImmediateReworkRate"].replace([np.inf, -np.inf], np.nan).mean()) if "ImmediateReworkRate" in df.columns else float('nan')

    # Build table HTML rows
    rows_html = []
    for _, r in df.iterrows():
        date_str = r["Date"].strftime("%Y-%m-%d %H:%M") if pd.notna(r["Date"]) else ""
        files = int(r.get("FilesTouched", 0)) if not pd.isna(r.get("FilesTouched", np.nan)) else 0
        lines = int(r.get("LinesAdded", 0)) if not pd.isna(r.get("LinesAdded", np.nan)) else 0
        surv = "" if pd.isna(r["SurvivalRate"]) else f"{float(r['SurvivalRate']):.3f}"
        immd = "" if pd.isna(r["ImmediateReworkRate"]) else f"{float(r['ImmediateReworkRate']):.3f}"
        qi = "" if pd.isna(r["AI_Quality_Index"]) else f"{float(r['AI_Quality_Index']):.3f}"
        rows_html.append(f"<tr><td>{date_str}</td><td>{files}</td><td>{lines}</td><td>{surv}</td><td>{immd}</td><td>{qi}</td></tr>")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>AI Acceptance Dashboard</title>
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 20px; }}
h1 {{ margin-bottom: 0; }}
.subtitle {{ color: #555; margin-top: 4px; }}
.nav {{ display: flex; gap: 10px; margin-top: 20px; flex-wrap: wrap; }}
.tab-btn {{ padding: 8px 12px; border: 1px solid #ddd; border-radius: 8px; cursor: pointer; }}
.tab-btn.active {{ background: #f0f0f0; }}
.tab {{ display: none; margin-top: 16px; }}
.tab.active {{ display: block; }}
.card {{ border: 1px solid #eee; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
.kpi {{ display: grid; grid-template-columns: repeat(4, minmax(120px,1fr)); gap: 12px; margin-top: 12px; }}
.kpi .item {{ background: #fafafa; border: 1px solid #eee; border-radius: 10px; padding: 12px; }}
.kpi .item .label {{ color: #666; font-size: 12px; }}
.kpi .item .value {{ font-size: 20px; font-weight: 600; }}
img.chart {{ width: 100%; height: auto; border: 1px solid #eee; border-radius: 8px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #eee; padding: 8px; text-align: left; }}
th.sortable:hover {{ background: #f5f5f5; cursor: pointer; }}
small {{ color: #666; }}
</style>
</head>
<body>
<h1>AI Acceptance Dashboard</h1>
<div class="subtitle">Self-contained report from <code>{os.path.basename(csv_path)}</code></div>

<div class="kpi">
  <div class="item"><div class="label">Commits</div><div class="value">{total_commits}</div></div>
  <div class="item"><div class="label">Lines Added</div><div class="value">{total_lines}</div></div>
  <div class="item"><div class="label">Avg Survival</div><div class="value">{overall_sr:.3f}</div></div>
  <div class="item"><div class="label">Avg Immediate Rework</div><div class="value">{"" if np.isnan(overall_ir) else f"{overall_ir:.3f}"}</div></div>
</div>

<div class="nav">
  <div class="tab-btn active" data-tab="t1">Survival over Time</div>
  <div class="tab-btn" data-tab="t2">Immediate Rework over Time</div>
  <div class="tab-btn" data-tab="t3">LinesAdded vs SurvivalRate</div>
  <div class="tab-btn" data-tab="t4">AI Quality Index</div>
  <div class="tab-btn" data-tab="t5">Raw Data</div>
</div>

<div id="t1" class="tab active">
  <div class="card"><img class="chart" src="{charts['survival']}" alt="Survival over Time" /></div>
  <small>Solid line = per-commit; dashed = 7-day rolling mean.</small>
</div>

<div id="t2" class="tab">
  <div class="card"><img class="chart" src="{charts['immediate']}" alt="Immediate Rework Rate over Time" /></div>
  <small>Dashed = 7-day rolling mean.</small>
</div>

<div id="t3" class="tab">
  <div class="card">
    {"<img class='chart' src=\"%s\" alt='LinesAdded vs SurvivalRate' />" % charts['scatter'] if charts['scatter'] else "<em>No LinesAdded column available.</em>"}
  </div>
</div>

<div id="t4" class="tab">
  <div class="card"><img class="chart" src="{charts['qi']}" alt="AI Quality Index over Time" /></div>
  <small>AI_Quality_Index = SurvivalRate × (1 − ImmediateReworkRate)</small>
</div>

<div id="t5" class="tab">
  <div class="card">
    <table id="data">
      <thead>
        <tr>
          <th class="sortable" data-col="0">Date</th>
          <th class="sortable" data-col="1">FilesTouched</th>
          <th class="sortable" data-col="2">LinesAdded</th>
          <th class="sortable" data-col="3">SurvivalRate</th>
          <th class="sortable" data-col="4">ImmediateReworkRate</th>
          <th class="sortable" data-col="5">AI_Quality_Index</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </div>
  <small>Click column headers to sort ascending/descending.</small>
</div>

<script>
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});
(function() {
  const table = document.getElementById('data');
  const getCellValue = (tr, idx) => tr.children[idx].innerText || tr.children[idx].textContent;
  const comparer = (idx, asc) => (a, b) => ((v1, v2) => (
    (!isNaN(v1) && !isNaN(v2)) ? (v1 - v2) : v1.toString().localeCompare(v2)
  ))(getCellValue(asc ? a : b, idx), getCellValue(asc ? b : a, idx));
  Array.from(table.querySelectorAll('th.sortable')).forEach(th => th.addEventListener('click', (() => {
    const table = th.closest('table');
    Array.from(table.querySelectorAll('th')).forEach(h => h.classList.remove('active'));
    th.classList.add('active');
    Array.from(table.querySelectorAll('tr:nth-child(n+2)'))
      .sort(comparer(parseInt(th.dataset.col), this.asc = !this.asc))
      .forEach(tr => table.querySelector('tbody').appendChild(tr) );
  })));
})();
</script>

</body>
</html>"""
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(html)
    return html_out

if __name__ == "__main__":
    out = build_dashboard()
    print(out)

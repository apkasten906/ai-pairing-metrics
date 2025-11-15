import argparse
import base64
import html as html_module
import io
import json
import os
import re
from string import Template

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams.update(
    {
        "figure.figsize": (12, 4.5),
        "font.size": 9,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
    }
)


def _to_png_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def _slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "repo"


def _unique_id(base, used, seed):
    candidate = base or f"repo-{seed}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 2
    while f"{candidate}-{index}" in used:
        index += 1
    final = f"{candidate}-{index}"
    used.add(final)
    return final


def _format_float(value):
    if value is None:
        return ""
    try:
        if np.isnan(value):
            return ""
    except TypeError:
        pass
    return f"{float(value):.3f}"


def _normalize_dataset_specs(default_csv, datasets):
    if datasets:
        specs = []
        for item in datasets:
            if "=" not in item:
                raise ValueError("Dataset arguments must use the format 'Display Name=path/to.csv'.")
            label, path = item.split("=", 1)
            label = label.strip()
            path = path.strip()
            if not label or not path:
                raise ValueError(f"Invalid dataset specification: {item}")
            specs.append((label, path))
        return specs
    display_name = os.path.splitext(os.path.basename(default_csv))[0] or "ai_acceptance_metrics"
    return [(display_name, default_csv)]


def _prepare_dataset(label, csv_path):
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

    fig1 = plt.figure()
    plt.plot(df["Date"], df["SurvivalRate"], marker="o", linestyle="-")
    if x_roll is not None:
        plt.plot(x_roll, roll_sr, linestyle="--")
    plt.title("Survival Rate over Time")
    plt.xlabel("Date")
    plt.ylabel("SurvivalRate (0-1)")
    plt.grid(True, alpha=0.3)
    charts["survival"] = _to_png_b64(fig1)

    fig2 = plt.figure()
    plt.plot(df["Date"], df["ImmediateReworkRate"], marker="o", linestyle="-")
    if x_roll is not None:
        plt.plot(x_roll, roll_ir, linestyle="--")
    plt.title("Immediate Rework Rate over Time")
    plt.xlabel("Date")
    plt.ylabel("ImmediateReworkRate (0-1)")
    plt.grid(True, alpha=0.3)
    charts["immediate"] = _to_png_b64(fig2)

    if "LinesAdded" in df.columns:
        fig3 = plt.figure()
        plt.scatter(df["LinesAdded"], df["SurvivalRate"])
        plt.title("Churn Correlation: LinesAdded vs SurvivalRate")
        plt.xlabel("LinesAdded per Commit")
        plt.ylabel("SurvivalRate (0-1)")
        plt.grid(True, alpha=0.3)
        charts["scatter"] = _to_png_b64(fig3)
    else:
        charts["scatter"] = ""

    fig4 = plt.figure()
    plt.plot(df["Date"], df["AI_Quality_Index"], marker="o", linestyle="-")
    if x_roll is not None:
        plt.plot(x_roll, roll_qi, linestyle="--")
    plt.title("AI Quality Index over Time")
    plt.xlabel("Date")
    plt.ylabel("AI_Quality_Index (0-1)")
    plt.grid(True, alpha=0.3)
    charts["qi"] = _to_png_b64(fig4)

    total_commits = len(df)
    total_lines = int(df["LinesAdded"].fillna(0).sum()) if "LinesAdded" in df.columns else 0
    overall_sr = float(df["SurvivalRate"].replace([np.inf, -np.inf], np.nan).mean()) if len(df) else 0.0
    if "ImmediateReworkRate" in df.columns:
        overall_ir = float(df["ImmediateReworkRate"].replace([np.inf, -np.inf], np.nan).mean())
    else:
        overall_ir = float("nan")

    rows_html = []
    for _, r in df.iterrows():
        date_str = r["Date"].strftime("%Y-%m-%d %H:%M") if pd.notna(r["Date"]) else ""
        files = int(r.get("FilesTouched", 0)) if not pd.isna(r.get("FilesTouched", np.nan)) else 0
        lines = int(r.get("LinesAdded", 0)) if not pd.isna(r.get("LinesAdded", np.nan)) else 0
        surv = _format_float(r["SurvivalRate"])
        immd = _format_float(r["ImmediateReworkRate"])
        qi = _format_float(r["AI_Quality_Index"])
        row = (
            "<tr>"
            f"<td>{html_module.escape(date_str)}</td>"
            f"<td>{html_module.escape(str(files))}</td>"
            f"<td>{html_module.escape(str(lines))}</td>"
            f"<td>{html_module.escape(surv)}</td>"
            f"<td>{html_module.escape(immd)}</td>"
            f"<td>{html_module.escape(qi)}</td>"
            "</tr>"
        )
        rows_html.append(row)

    return {
        "label": label,
        "source": os.path.basename(csv_path),
        "charts": charts,
        "kpi": {
            "commits": str(total_commits),
            "lines": str(total_lines),
            "survival": _format_float(overall_sr),
            "immediate": _format_float(overall_ir),
        },
        "tableRows": "\n        ".join(rows_html),
    }


def build_dashboard(csv_path="ai_acceptance_metrics.csv", html_out="ai_acceptance_dashboard.html", datasets=None):
    dataset_specs = _normalize_dataset_specs(csv_path, datasets)
    if not dataset_specs:
        raise ValueError("At least one dataset must be provided.")

    repo_payloads = {}
    option_tags = []
    used_ids = set()
    default_repo_id = None

    for idx, (label, path) in enumerate(dataset_specs, start=1):
        payload = _prepare_dataset(label, path)
        repo_id = _unique_id(_slugify(label), used_ids, idx)
        payload["id"] = repo_id
        repo_payloads[repo_id] = payload
        if default_repo_id is None:
            default_repo_id = repo_id
        selected_attr = " selected" if repo_id == default_repo_id else ""
        option_tags.append(f'<option value="{repo_id}"{selected_attr}>{html_module.escape(label)}</option>')

    initial_payload = repo_payloads[default_repo_id]
    options_html = "\n      ".join(option_tags)
    repo_data_json = json.dumps(repo_payloads).replace("</", "<\\/")

    initial_repo_label = html_module.escape(initial_payload["label"])
    initial_repo_source = html_module.escape(initial_payload["source"])
    initial_kpi = initial_payload["kpi"]
    initial_table_rows = initial_payload["tableRows"]
    scatter_src = initial_payload["charts"].get("scatter", "")
    scatter_img_extra_class = "" if scatter_src else " hidden"
    scatter_empty_class_attr = ' class="hidden"' if scatter_src else ""

    html_template = Template("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>AI Acceptance Dashboard</title>
<style>
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 20px; }
h1 { margin-bottom: 0; }
.subtitle { color: #555; margin-top: 4px; }
.nav { display: flex; gap: 10px; margin-top: 20px; flex-wrap: wrap; }
.tab-btn { padding: 8px 12px; border: 1px solid #ddd; border-radius: 8px; cursor: pointer; }
.tab-btn.active { background: #f0f0f0; }
.tab { display: none; margin-top: 16px; }
.tab.active { display: block; }
.card { border: 1px solid #eee; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.kpi { display: grid; grid-template-columns: repeat(4, minmax(120px,1fr)); gap: 12px; margin-top: 12px; }
.kpi .item { background: #fafafa; border: 1px solid #eee; border-radius: 10px; padding: 12px; }
.kpi .item .label { color: #666; font-size: 12px; }
.kpi .item .value { font-size: 20px; font-weight: 600; }
img.chart { width: 100%; height: auto; border: 1px solid #eee; border-radius: 8px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #eee; padding: 8px; text-align: left; }
th.sortable:hover { background: #f5f5f5; cursor: pointer; }
small { color: #666; }
.repo-switcher { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }
.repo-switcher-controls { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.repo-switcher select { padding: 6px 8px; border-radius: 6px; border: 1px solid #ccc; min-width: 200px; }
.repo-switcher button { padding: 6px 12px; border-radius: 6px; border: 1px solid #ccc; background: #fff; cursor: pointer; }
.repo-switcher button:hover { background: #f5f5f5; }
.hidden { display: none !important; }
</style>
</head>
<body>
<h1>AI Acceptance Dashboard</h1>
<div class="subtitle">Self-contained report for <strong id="repoName">${initial_repo_label}</strong> from <code id="repoSource">${initial_repo_source}</code></div>

<div class="repo-switcher card">
  <label for="repoSelect">Target repository</label>
  <div class="repo-switcher-controls">
    <select id="repoSelect">
      ${options_html}
    </select>
    <button id="repoApply" type="button">Load metrics</button>
  </div>
</div>

<div class="kpi">
  <div class="item"><div class="label">Commits</div><div class="value" id="kpi-commits">${initial_kpi_commits}</div></div>
  <div class="item"><div class="label">Lines Added</div><div class="value" id="kpi-lines">${initial_kpi_lines}</div></div>
  <div class="item"><div class="label">Avg Survival</div><div class="value" id="kpi-survival">${initial_kpi_survival}</div></div>
  <div class="item"><div class="label">Avg Immediate Rework</div><div class="value" id="kpi-immediate">${initial_kpi_immediate}</div></div>
</div>

<div class="nav">
  <div class="tab-btn active" data-tab="t1">Survival over Time</div>
  <div class="tab-btn" data-tab="t2">Immediate Rework over Time</div>
  <div class="tab-btn" data-tab="t3">LinesAdded vs SurvivalRate</div>
  <div class="tab-btn" data-tab="t4">AI Quality Index</div>
  <div class="tab-btn" data-tab="t5">Raw Data</div>
</div>

<div id="t1" class="tab active">
  <div class="card"><img id="chart-survival" class="chart" src="${chart_survival}" alt="Survival over Time" /></div>
  <small>Solid line = per-commit; dashed = 7-day rolling mean.</small>
</div>

<div id="t2" class="tab">
  <div class="card"><img id="chart-immediate" class="chart" src="${chart_immediate}" alt="Immediate Rework Rate over Time" /></div>
  <small>Dashed = 7-day rolling mean.</small>
</div>

<div id="t3" class="tab">
  <div class="card">
    <img id="chart-scatter" class="chart${scatter_img_extra_class}" src="${chart_scatter}" alt="LinesAdded vs SurvivalRate" />
    <em id="scatter-empty"${scatter_empty_class_attr}>No LinesAdded column available.</em>
  </div>
</div>

<div id="t4" class="tab">
  <div class="card"><img id="chart-qi" class="chart" src="${chart_qi}" alt="AI Quality Index over Time" /></div>
  <small>AI_Quality_Index = SurvivalRate * (1 - ImmediateReworkRate)</small>
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
      <tbody id="data-body">
        ${initial_table_rows}
      </tbody>
    </table>
  </div>
  <small>Click column headers to sort ascending/descending.</small>
</div>

<script>
const REPO_DATA = ${repo_data_json};
const DEFAULT_REPO = "${default_repo_id}";
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
  const comparer = (idx, asc) => (a, b) => {
    const v1 = getCellValue(asc ? a : b, idx);
    const v2 = getCellValue(asc ? b : a, idx);
    const n1 = parseFloat(v1);
    const n2 = parseFloat(v2);
    if (!isNaN(n1) && !isNaN(n2)) {
      return n1 - n2;
    }
    return v1.localeCompare(v2);
  };
  Array.from(table.querySelectorAll('th.sortable')).forEach(th => {
    th.addEventListener('click', () => {
      const idx = parseInt(th.dataset.col, 10);
      const asc = th.dataset.sortOrder !== 'asc';
      th.dataset.sortOrder = asc ? 'asc' : 'desc';
      const rows = Array.from(table.querySelector('tbody').querySelectorAll('tr'));
      rows
        .sort(comparer(idx, asc))
        .forEach(tr => table.querySelector('tbody').appendChild(tr));
      table.querySelectorAll('th.sortable').forEach(header => header.classList.remove('active'));
      th.classList.add('active');
    });
  });
})();
(function() {
  const repoSelect = document.getElementById('repoSelect');
  const repoApply = document.getElementById('repoApply');
  const repoName = document.getElementById('repoName');
  const repoSource = document.getElementById('repoSource');
  const tableBody = document.getElementById('data-body');
  const scatterImg = document.getElementById('chart-scatter');
  const scatterEmpty = document.getElementById('scatter-empty');
  const kpis = {
    commits: document.getElementById('kpi-commits'),
    lines: document.getElementById('kpi-lines'),
    survival: document.getElementById('kpi-survival'),
    immediate: document.getElementById('kpi-immediate')
  };
  function renderRepo(repoId) {
    const data = REPO_DATA[repoId];
    if (!data) {
      return;
    }
    repoName.textContent = data.label;
    repoSource.textContent = data.source;
    kpis.commits.textContent = data.kpi.commits;
    kpis.lines.textContent = data.kpi.lines;
    kpis.survival.textContent = data.kpi.survival;
    kpis.immediate.textContent = data.kpi.immediate;
    document.getElementById('chart-survival').src = data.charts.survival;
    document.getElementById('chart-immediate').src = data.charts.immediate;
    document.getElementById('chart-qi').src = data.charts.qi;
    if (data.charts.scatter) {
      scatterImg.src = data.charts.scatter;
      scatterImg.classList.remove('hidden');
      scatterEmpty.classList.add('hidden');
    } else {
      scatterImg.classList.add('hidden');
      scatterEmpty.classList.remove('hidden');
    }
    tableBody.innerHTML = data.tableRows || "";
  }
  repoApply.addEventListener('click', () => renderRepo(repoSelect.value));
  repoSelect.addEventListener('keypress', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      renderRepo(repoSelect.value);
    }
  });
  if (DEFAULT_REPO in REPO_DATA) {
    repoSelect.value = DEFAULT_REPO;
    renderRepo(DEFAULT_REPO);
  }
})();
</script>

</body>
</html>""")

    html_content = html_template.substitute(
        initial_repo_label=initial_repo_label,
        initial_repo_source=initial_repo_source,
        options_html=options_html,
        initial_kpi_commits=initial_kpi["commits"],
        initial_kpi_lines=initial_kpi["lines"],
        initial_kpi_survival=initial_kpi["survival"],
        initial_kpi_immediate=initial_kpi["immediate"],
        chart_survival=initial_payload["charts"]["survival"],
        chart_immediate=initial_payload["charts"]["immediate"],
        chart_scatter=scatter_src,
        scatter_img_extra_class=scatter_img_extra_class,
        scatter_empty_class_attr=scatter_empty_class_attr,
        chart_qi=initial_payload["charts"]["qi"],
        initial_table_rows=initial_table_rows,
        repo_data_json=repo_data_json,
        default_repo_id=default_repo_id,
    )

    with open(html_out, "w", encoding="utf-8") as f:
        f.write(html_content)
    return html_out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the AI Acceptance dashboard HTML report.")
    parser.add_argument("--csv", dest="csv_path", default="ai_acceptance_metrics.csv", help="Path to a CSV file (used when --dataset is omitted).")
    parser.add_argument("--out", dest="html_out", default="ai_acceptance_dashboard.html", help="Destination HTML report path.")
    parser.add_argument("--dataset", action="append", help="Repeatable 'Display Name=path/to.csv' entries to embed multiple repos.")
    args = parser.parse_args()
    output_path = build_dashboard(csv_path=args.csv_path, html_out=args.html_out, datasets=args.dataset)
    print(output_path)

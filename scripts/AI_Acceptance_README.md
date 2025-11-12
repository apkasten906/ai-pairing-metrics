
# AI "Corrected Acceptance" Metrics (PowerShell)

This script computes **survival-based AI acceptance metrics** from your local Git history — a practical proxy for *"how much AI-generated code survives after your fixes and reviews?"*

> Why survival? We can't tag AI lines directly without telemetry. If you primarily scaffold with AI, the fraction of **added lines that still exist in `HEAD`** is a strong signal of *corrected acceptance* and long-term quality.

## What it measures

- **SurvivalRate (per-commit):** `SurvivedInHEAD / LinesAdded`  
  Lines you added in a commit that still exist (unchanged) in the current `HEAD`.  
  Higher = your accepted code holds up after later fixes/reviews.

- **ImmediateReworkRate:** Fraction of those lines missing in the **next commit touching the same file within N minutes** (default 90).  
  Higher = you often accept then quickly fix/replace within the same session.

- **Overall summary:** Totals across commits over the chosen window.

> Note: This is language-agnostic and approximate. It ignores whitespace-only changes and (optionally) comment-only lines. It matches lines by exact string, so refactors or minor edits count as changed.

## Installation & Usage

1. Save the script (or download the provided file) as `ai_acceptance_metrics.ps1` in your repo root.
2. Open **PowerShell** and run:

```powershell
# Example: last 30 days, ignore comments, minimum line length 5 chars
.\ai_acceptance_metrics.ps1 -SinceDays 30 -IgnoreComments -MinLineLength 5 -Output ai_acceptance_metrics.csv
```

Optional parameters:
- `-Author "Your Name"` to filter to your commits.
- `-Branch "HEAD"` to compare survival against a different ref.
- `-ImmediateWindowMinutes 60` to tune the immediate rework window.

## Outputs
- `ai_acceptance_metrics.csv` — per-commit metrics (Date, FilesTouched, LinesAdded, SurvivedInHEAD, SurvivalRate, ImmediateReworkRate).
- `ai_acceptance_summary.txt` — overall summary and quick ratios.

## Interpreting Results

- **Overall SurvivalRate**  
  - **≥ 0.70**: Strong corrected acceptance; your AI scaffolds are sticking.  
  - **0.50–0.69**: Healthy — typical for iterative refactoring.  
  - **< 0.50**: Lots of churn; consider adding tighter specs/prompt patterns.

- **ImmediateReworkRate**  
  - **≥ 0.30**: You often accept then fix right away. Consider spending 30–60s on a targeted re-prompt for critical chunks.  
  - **< 0.15**: Minimal churn — your first-pass scaffolds are close to final.

## Tips to Improve
- Translate recurring fixes into your **spec templates** (prompt once, benefit forever).
- Add **auto-lint/test on save or pre-commit** to catch anti-patterns early.
- For large diffs, consider **"explain + propose" in chat** before accepting a big block.

---

This is intentionally transparent and offline — it reads only your `git` history and the current working tree.

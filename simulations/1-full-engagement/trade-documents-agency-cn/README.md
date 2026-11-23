# Community case · 进出口代理单证一致性（Trade Document Consistency, CN）

> **Unofficial community contribution.** This case was built as a course exercise by applying the
> frameworks in `fde-simulation` to a synthetic Chinese trade-document agency scenario.
> All customer names, volumes, durations and failure cases are **synthetic training data**.
> The case does not represent real authorization, business execution, or customer acceptance.

## Why this case

Most FDE practice material is set in insurance or finance. This case adds a **regulated
document-handling workflow in an import/export agency**, where the hard part is not model
quality but governance: who may confirm a conclusion, which fields may be read, and how a
stale document version is prevented from overwriting a confirmed one.

The learner works through the familiar arc on a new domain:

- Six stakeholders with explicit decision rights (only the business owner may confirm; the
  model role has `can_confirm: false` by configuration).
- A five-stage chain: `客户提供 → 单证检查 → 人工确认 → 委托作业 → 归档`.
- Acceptance framed as **50 sample packs with every planted discrepancy located back to the
  original document field**, each linked to its source and a human review record.
- Seven hard data redlines, each traceable to a fact ID (`f00`–`f54`) and to a concrete
  implementation point.

## Contents

| Path | What it is |
|---|---|
| `CASE_BRIEF.html` | Customer brief / scenario reading page (Chinese) |
| `discovery/BUSINESS_DISCOVERY_REPORT.md` | Task 1–3 discovery answers, reference comparison and scored feedback |
| `discovery/FIELD_RESEARCH_REPORT.md` | Role interviews, as-is process, 4-source convergence |
| `discovery/DISCOVERY_REPORT.md` | Requirement discovery report: P0/P1 needs, evidence ledger, gaps |
| `discovery/discovery-report.json` / `.csv` | Machine-readable version of the discovery report |
| `discovery/业务发现访谈问题库.html` | Interview question bank |
| `discovery/利益相关者资料与分工.html` | Stakeholder profiles and responsibilities |
| `discovery/现状信息请求表.html` | Information request form used in the exercise |
| `discovery/现状流程图与异常路径.html` | As-is flow diagram with three exception paths |
| `solution/TECHNICAL_DESIGN.md` | 10-chapter technical design: redlines, data model, APIs, decisions |
| `solution/TECHNICAL_DESIGN_PROMPT.md` | Prompt used to produce the design doc |
| `prototype/` | Python 3.11+ / FastAPI / SQLite prototype (stage 1 implemented) |

## Run the prototype

```bash
cd prototype
python -m pip install -r requirements.txt
python scripts/run_harness.py        # env check + full pytest; exit code 0 = pass
python -m uvicorn app.main:app --reload --port 8000
```

The harness currently runs **6/6 passing tests** (health, import idempotency, pack query
structure, unknown-role `FORBIDDEN`, `NOT_FOUND`, audit trail written). Verified on
Python 3.13.

## Mapping to this repository's frameworks

| Framework | Where it shows up |
|---|---|
| 4-source convergence | `discovery/FIELD_RESEARCH_REPORT.md`, `discovery/DISCOVERY_REPORT.md` |
| Workflow decomposition | Five-stage chain in `solution/TECHNICAL_DESIGN.md` §3.3 |
| Outcome Risk Matrix | Candidate-need / irreversible-risk section of `discovery/DISCOVERY_REPORT.md` |
| Trust surface design | Confirmation rights, audit trail, `config.yaml` `roles` / `redlines` |
| The agent harness | `prototype/scripts/run_harness.py` |

## Status and known gaps

- Stage 1 (config, five tables, unified response, read-only importer, three endpoints) is implemented and tested.
- Stages 2–4 (checklist engine, manual-queue transitions, audit search and 50-pack acceptance runner) are **specified in the technical design but not yet implemented**; the UI shell is in `prototype/web/`.
- The exercise reports contain scored feedback from the course grader. They are included as
  learning artifacts, not as official reference answers.
- All figures (e.g. 220 packs/month, 42 min/pack) are explicitly labelled synthetic and must
  not be used as a business baseline.

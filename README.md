# FlowState

FlowState is an autonomous research workflow for the TikTok TechJam 2026 Track #2 KuaiRand-Pure recommender-system challenge. It reads the locked challenge rules, validates the supplied data and official evaluator, reproduces the organizer FM baseline, plans one bounded experiment at a time, trains and scores it, records every result and recovery action, then preserves the validation-selected submission artifact.

The workflow ranks each user's supplied video candidates for the `long_view` label. It uses the organizer's `evaluate.py` for GAUC and nDCG@5, keeps test labels out of development, and writes the required `row_id,user_id,video_id,score` prediction format.

> **Dataset notice:** KuaiRand data, checkpoints, local research state, and credentials are intentionally not included. Download the data from the official source and keep it local; the repository is configured not to commit it.

## What is included

- `src/flowstate/` — workflow, data validation, experiment execution, recovery, ledger, submission packaging, API, and CLI code.
- `ui/` — React/Vite observer for monitoring a local FlowState session.
- `configs/` — challenge rules, baseline, experiment, runtime, and budget settings.
- `kuairand-starter-kit/` — organizer reference loader, evaluator, FM baseline, and submission checker.
- `tests/` — focused workflow, data, recovery, API, knowledge, and MCP contract tests.
- `docs/architecture/` — architecture, diagrams, and research rationale.

## Requirements

| Tool | Supported versions | Purpose |
| --- | --- | --- |
| Python | 3.12.x | FlowState backend and research workflow |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | current | Python environment and locked dependency install |
| [Node.js](https://nodejs.org/) | 20 LTS or newer | local observer UI |
| npm | bundled with Node.js | UI dependency install and build |
| NVIDIA CUDA GPU | optional for smoke checks; recommended for full research runs | model training |

The backend runs on Windows, macOS, and Linux. The configured CUDA PyTorch wheel is used on Windows and Linux. On macOS, PyTorch uses the platform-supported backend; full CUDA training is not available.

## Setup and local deployment

### 1. Get the code

```bash
git clone https://github.com/Dheemant19/TikTok-TechJam_RGB.git
cd TikTok-TechJam_RGB
```

### 2. Install Python dependencies with uv

**Windows (PowerShell):**

```powershell
irm https://astral.sh/uv/install.ps1 | iex
uv sync --extra test
```

**macOS or Linux (Terminal):**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra test
```

If `uv` is not available after installation, close and reopen the terminal. The committed `uv.lock` makes dependency resolution repeatable.

### 3. Install the observer UI

Install Node.js 20 LTS or newer from [nodejs.org](https://nodejs.org/), then run:

```bash
cd ui
npm ci
cd ..
```

### 4. Download the permitted KuaiRand-Pure data

Obtain KuaiRand-Pure from its official distribution, preserving the source filenames. Place the files in a local directory such as `KuaiRand-Pure/data/` in the repository root. Do not commit this directory or use any external training data.

The expected files include:

```text
log_standard_4_08_to_4_21_pure.csv
log_standard_4_22_to_5_08_pure.csv
log_random_4_22_to_5_08_pure.csv
user_features_pure.csv
video_features_basic_pure.csv
video_features_statistic_pure.csv
```

### 5. Configure local paths and model access

Copy the example file and edit only the values on the right side of `=`:

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

**macOS or Linux (Terminal):**

```bash
cp .env.example .env
```

Set `KUAIRAND_DATA_DIR` to the directory from step 4. An autonomous run also requires an Azure AI Foundry endpoint, key, API version, and the three deployment names shown in `.env.example`. `GITHUB_TOKEN` is optional and only enables authenticated GitHub research lookup.

### 6. Validate the local contract

```bash
uv run flowstate validate
```

This checks the challenge configuration and evaluator safety rules without starting a training run.

### 7. Run locally

Start the backend in one terminal:

```bash
uv run flowstate serve-ui
```

Start the UI in a second terminal:

```bash
cd ui
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server forwards `/api` requests to the local backend at `http://127.0.0.1:8000`.

For a production-style local UI build:

```bash
cd ui
npm run build
cd ..
uv run flowstate serve-ui
```

Open `http://127.0.0.1:8000`.

## Reproducing a research run

Use only the configured train/validation splits during development. The commands below create local artifacts under ignored `artifacts/` and `state/` directories.

```bash
# Validate data, split rules, and the organizer evaluator.
uv run flowstate validate

# Profile the configured data and build train-fitted transforms.
uv run flowstate profile

# Reproduce the organizer FM baseline with its configured seeds.
uv run flowstate reproduce-baseline

# Run the bounded autonomous research loop.
uv run flowstate run
```

After a completed session, inspect the immutable ledger and package the validation-selected artifact:

```bash
uv run flowstate report <session-id>
uv run flowstate package-submission <session-id> --confirmation <session-id>
```

The package step generates predictions once from the validation-best checkpoint and calls the organizer submission checker. Verify a standalone file with:

```bash
uv run python kuairand-starter-kit/submit.py <submission.csv> --data_dir "$KUAIRAND_DATA_DIR" --split test --check
```

On Windows PowerShell, use `$env:KUAIRAND_DATA_DIR` instead of `$KUAIRAND_DATA_DIR`.

## Recorded validation result

The completed session selected `E3_mmoe_longview_click_bce-a77ffb2b` as its validation-best artifact. It uses a compact multi-task mixture-of-experts model: `is_click` is a training-only auxiliary target, and the `long_view` head alone produces inference scores from the permitted categorical features.

| Validation metric | Reproduced FM mean (5 seeds) | Selected run | Change |
| --- | ---: | ---: | ---: |
| GAUC | 0.667400 | 0.671071 | +0.003671 |
| nDCG@5 | 0.535744 | 0.537599 | +0.001855 |
| Primary `(GAUC + nDCG@5) / 2` | 0.601572 | 0.604335 | **+0.002763** |

These are fixed-split validation measurements from the organizer evaluator, recorded in the local ledger. They are not hidden-test scores. The final prediction artifact passed the organizer schema and row-alignment check for 170,588 test rows.

## Verification

```bash
# Python workflow contracts
uv run pytest

# UI unit tests and production build
cd ui
npm test
npm run build
```

## Limitations and next steps

- Full runs need the official data, Azure model access, and a capable GPU; they are not practical on every laptop.
- The agent uses a bounded experiment budget. More compute would allow repeated-seed confirmation of small validation gains and more focused tests of ranking losses and temporal or sequential features.
- The browser observer is local by design. It does not expose credentials, raw data, checkpoints, validation labels, or test labels.


## Team contributions

Team Members:
Dheemant Rastogi,
Arushi Verma and
Sanjana Yalamanchili.

Every member has contributed equally to the development of this project.

## Best-run demo

A separate, data-free mockup shows the completed metrics and audit trail from the best FlowState session on KuaiRand - Pure dataset. 

**Vercel demo:** `https://flowstate-demo-nine.vercel.app/`

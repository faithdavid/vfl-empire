# 🏛️ VFL Empire — Prediction Engine

**Lord FaithDavid's VFL Prediction System**  
42,464 match results · 7,024 odds entries · MuZero RL · Survivorship Bias Analysis

## 📁 Structure

```
vfl-empire/
├── data/
│   ├── consolidated/   # The 3 master datasets:
│   │   ├── all_consolidated_joined.json    (1,264 matches — odds + outcomes)
│   │   ├── all_consolidated_odds.json      (7,024 odds entries)
│   │   └── all_consolidated_results.json   (42,464 full results)
│   ├── databases/      # SQLite databases (history.db, sovereign.db)
│   └── raw/            # Raw HAR captures & extracted responses
├── notebooks/
│   └── vfl_empire_gpu.ipynb     # Colab GPU training + bullet-hole analysis
├── scripts/            # Analysis engines (VFL Bayesian, Wald filter, etc.)
├── models/             # Trained models (XGBoost, ONNX, JSON configs)
├── results/            # Analysis outputs + MuZero CPU training run
└── archive/            # Logs and historical artifacts
```

## 🚀 Quick Start — Google Colab (GPU)

1. Open `notebooks/vfl_empire_gpu.ipynb` in Google Colab:
   - [Open in Colab](https://colab.research.google.com/github/YOUR_USER/vfl-empire/blob/main/notebooks/vfl_empire_gpu.ipynb)
   - Or: File → Open Notebook → GitHub → paste this repo URL

2. **Runtime → Change runtime type → T4 GPU**

3. **Run All** — The notebook will:
   - ✅ Auto-load all 42K results + 7K odds
   - ✅ Train MuZero on GPU (50K steps ~15 min)
   - ✅ Run **Survivorship Bias Analysis** (bullet holes = missed predictions)
   - ✅ Save model to Google Drive

## 🎯 The Wald Survivorship Bias Insight

> *"During WW2, engineers wanted to armor the wings of returning planes (where bullet holes clustered). Statistician Abraham Wald said: the planes that came back are the ones hit in non-critical areas. The ones that went down — we never see them."*

**Our application:** Our missed predictions are the downed planes. Instead of optimizing what already works, we study every miss to find the real weaknesses — by league, odds range, upset type, and market confidence.

## 📊 Key Metrics

| Dataset | Size | Source |
|---|---|---|
| Full match results | 42,464 | HAR captures + GitHub |
| Odds entries | 7,024 | Msport API |
| Joined (odds + outcome) | 1,264 | Matched records |
| Seasons covered | 186 | Full historical |

## 🧠 Built With

- **MuZero** — DeepMind's model-based RL (werner-duvaud/muzero-general)
- **Poisson Model** — Goal-based scoring rate estimation
- **VFL Engine Model v2** — PRNG-weighted stochastic prediction
- **Bayesian Calibration** — Confidence tier validation

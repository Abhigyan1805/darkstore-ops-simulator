#!/usr/bin/env bash
# Download the two public datasets into data/raw (git-ignored).
# Needs the Kaggle CLI and a token: export KAGGLE_API_TOKEN=... (or ~/.kaggle/kaggle.json).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw/instacart data/raw/bigbasket
if [ -z "$(ls data/raw/instacart/*.csv 2>/dev/null)" ]; then
  kaggle datasets download -d yasserh/instacart-online-grocery-basket-analysis-dataset \
    -p data/raw/instacart --unzip
fi
if [ -z "$(ls data/raw/bigbasket/*.csv 2>/dev/null)" ]; then
  kaggle datasets download -d surajjha101/bigbasket-entire-product-list-28k-datapoints \
    -p data/raw/bigbasket --unzip
fi
ls -la data/raw/instacart data/raw/bigbasket

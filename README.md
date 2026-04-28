# Bean_Annotator

Streamlit app for annotating bean crop images with quality severity scores and defect regions.

## Features

- 1-5 overall bean severity scale
- Zoomable and pannable image inspection
- Rectangle and polygon defect annotation
- Defect type labels and notes
- Skip option for unclear beans
- Per-bean JSON annotation files
- Summary `labels.csv`
- Severity-colored bordered output images

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Run

```bash
streamlit run annotate_beans.py --server.port 8501
```

## Outputs

The app writes results into the selected output folder:

- `annotations/*.json`
- `labels.csv`
- `labeled/severity_*/`


# Bean Quality Annotator

Streamlit app for annotating bean crop images with quality severity scores and defect regions.

## Features

- 1-5 overall bean severity scale
- Zoomable and pannable image inspection
- Rectangle and polygon defect annotation
- Defect type labels and notes
- Skip option for unclear beans
- In-session annotation records
- Downloadable `annotations.zip` and `labels.csv`

## Local Run

```bash
python3 -m pip install -r requirements.txt
python3 -m streamlit run annotate_beans.py --server.port 8501
```

Upload bean images from the start screen. When finished, download `annotations.zip` and `labels.csv` from the sidebar.

## Deploy On Streamlit Community Cloud

1. Push this folder to a GitHub repository.
2. In Streamlit Community Cloud, create a new app from that repository.
3. Set the entrypoint file to:

```text
Annotation_GUI/annotate_beans.py
```

4. In Advanced settings, select Python `3.12`.
5. Deploy.

The dependency file is next to the entrypoint, so Streamlit Cloud will install the packages from `Annotation_GUI/requirements.txt`.

## Important Deployment Note

The deployed app uses browser uploads and Streamlit session state. It does not use a database or persistent server storage. Refreshing the page or restarting the app clears the active session, so download `annotations.zip` and `labels.csv` regularly.

To resume later, upload the same images plus the exported JSON annotation files from `annotations.zip`.

## Outputs

- `annotations.zip`: one JSON file per annotated bean
- `labels.csv`: summary table with severity, skip status, defect count, notes, timestamp, and annotator

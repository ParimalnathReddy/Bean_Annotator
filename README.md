# Bean Quality Annotator

Streamlit app for annotating bean crop images with quality severity scores and defect regions.


checkout: https://parimalnathreddy-bean-annotator-annotation-h3zurb.streamlit.app/

## Features

- 1-5 overall bean severity scale
- Zoomable and pannable image inspection
- Polygon defect annotation
- Defect type labels and notes
- Skip option for unclear beans
- In-session annotation records
- Single downloadable project bundle with images, detailed annotations, and `labels.csv`

## Local Run

```bash
python3 -m pip install -r requirements.txt
python3 -m streamlit run annotate_beans.py --server.port 8501
```

Upload bean images from the start screen. When finished, download the project bundle from the sidebar. The ZIP filename is based on the image stem, for example `0003_annotations_bundle.zip`.

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

The deployed app uses browser uploads and Streamlit session state. It does not use a database or persistent server storage. Refreshing the page or restarting the app clears the active session, so download the project bundle regularly.

To resume later, upload the saved project bundle. The bundle includes the images and the annotation details needed to continue.

## Outputs

- `<image_stem>_annotations_bundle.zip`: one ZIP containing `manifest.json`, `labels.csv`, `images/*.png`, and `annotations/*.json`

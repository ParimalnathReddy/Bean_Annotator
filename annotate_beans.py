"""Launcher for the Bean Quality Annotator.

Run:
    streamlit run annotate_beans.py --server.port 8501
"""

from annotation import main


if __name__ == "__main__":
    main()

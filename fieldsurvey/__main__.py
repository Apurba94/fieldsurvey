"""Start the app: python -m fieldsurvey [data.db] [--port 8032]"""
import sys

from .fieldkit import main_cli
from .web import create_app

sys.exit(main_cli(create_app, "survey.db", 8032, sys.argv))

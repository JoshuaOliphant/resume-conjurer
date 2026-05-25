# ABOUTME: pytest conftest that puts the plugin's scripts dir on sys.path.
# ABOUTME: Lets tests import lint, composer, stitch, init_app, new_workspace directly.
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "conjurer" / "skills" / "conjurer" / "scripts"
sys.path.insert(0, str(SCRIPTS))

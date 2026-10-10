# ABOUTME: Makes shared plugin scripts importable for every web test module.
# ABOUTME: Removes dependence on the order in which pytest imports adapters.
from app.adapters.scripts_path import ensure_scripts_on_path

ensure_scripts_on_path()

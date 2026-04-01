"""
LTX-2 Character LoRA Training Data Automation Pipeline

Transforms movie files into high-quality, identity-focused,
bucketed training samples ready for LTX-2 LoRA training.
"""

from pathlib import Path

# Read version from VERSION file
__version__ = "0.2.0"
_version_file = Path(__file__).parent / "VERSION"
if _version_file.exists():
    __version__ = _version_file.read_text().strip()

"""Local Python path setup for the ADS1299 analysis tools.

The D: drive Python on this workstation stores third-party packages under
`D:/Lib/site-packages`, but that folder is not always present on sys.path.
Keeping this small hook beside the analysis scripts lets `python script.py`
find numpy/pandas/scipy/matplotlib without extra environment setup.
"""

from pathlib import Path
import sys


SITE_PACKAGES = Path("D:/Lib/site-packages")

if SITE_PACKAGES.exists():
    site_packages = str(SITE_PACKAGES)
    if site_packages not in sys.path:
        sys.path.append(site_packages)

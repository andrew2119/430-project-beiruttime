"""Catalog process discovery compatibility for additive lane fragments."""

import re
from bt_runtime import modules

LANE = r"(?:0[0-9]|1[0-9]|2[0-5])"


def configure():
    """Keep the shared loader's path, dependency and duplicate validation intact.

    Configure once before application or migration discovery. Missing fragments
    remain absent; no generated module list is required.
    """
    modules.MODULE_ID = re.compile(r"^L" + LANE + r"\.[a-z][a-z0-9.-]+$")
    modules.MIGRATION = re.compile(r"^L" + LANE + r"_[0-9]{4}_[a-z0-9_]+\.sql$")

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""GleanWise core."""

import os

# Privacy by default: no library in the dependency tree may phone home.
for _key, _value in {
    "DO_NOT_TRACK": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "ANONYMIZED_TELEMETRY": "False",
    "LITELLM_TELEMETRY": "False",
    "LITELLM_LOG": "ERROR",
    "ORT_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "SCARF_NO_ANALYTICS": "true",
}.items():
    os.environ.setdefault(_key, _value)

__version__ = "0.2.0"

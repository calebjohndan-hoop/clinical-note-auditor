"""Test-suite defaults.

With an LLM key in .env, app.extractor.extract_fields() defaults to HYBRID, which would make
every rule/stress test call the live API: on free tiers that is slow (this suite took 11
minutes once) and burns the daily token quota. So tests default to the deterministic regex
extractor. To deliberately run the suite against the LLM:

    $env:EXTRACTOR="hybrid"; python -m pytest tests -q        # (spends quota!)
"""
import os

os.environ.setdefault("EXTRACTOR", "regex")

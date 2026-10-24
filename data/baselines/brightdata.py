"""Bright Data, the second dated source for c11 (issue #47). NOT CONFIGURED: needs BRIGHT_DATA_API_KEY and Vidyut's OK
to spend. Same output as data.baselines.observations() rows with provider "brightdata", so baseline() needs no change."""
import os


class NotConfigured(RuntimeError):
    pass


def observations(skus=("rtx 5070 ti",)) -> list[dict]:
    if not os.environ.get("BRIGHT_DATA_API_KEY"):
        raise NotConfigured("BRIGHT_DATA_API_KEY is not set; Bright Data spend needs Vidyut's OK first")
    raise NotConfigured("Bright Data collector not wired yet: pick the dataset or scraper once the key and spend are approved")

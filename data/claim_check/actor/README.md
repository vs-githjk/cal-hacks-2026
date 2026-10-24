# Tech Bazaar claim check (Apify Actor, for a14)
Input `{"claims": [{id, text, kind, evidence_url}]}`; one dataset row per claim with `result` (verified, unverified, false), `evidence_url`, `checked_at`, `method`, `evidence_hash`, `reason`.
Publish (Abhinav): `./bundle.sh && apify push` from this folder (bundle copies the checker into `src/data/`, gitignored).
Status: the check logic is tested (`data/tests/test_claim_check.py`); this wrapper has **not yet run on Apify**. A local run failed on SDK dependency versions under Python 3.13 (pydantic, browserforge); the platform image is Python 3.12.

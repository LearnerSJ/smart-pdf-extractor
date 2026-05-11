"""Self-healing extraction system with three feedback loops.

Loop 1: Immediate Self-Retry (diagnostic_retry) — diagnoses extraction failures
         and retries with adjusted strategy when >50% abstentions.
Loop 2: Schema Learning (schema_learner) — tracks success rates per schema and
         triggers VLM-based refinement when performance drops below 70%.
Loop 3: Pattern Mining (pattern_miner) — aggregates failure patterns hourly and
         generates improvement suggestions for the admin dashboard.
"""

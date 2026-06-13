"""Ranker — the selection spine.

Stage 9. Account-mandate filter FIRST (a Suggestion whose family/instrument_class
isn't permitted for the account's pool/blocked_rules is never produced). Then
per-sleeve candidate generation, regime-blend scoring + tier multiplier
(Tier B 0.6x), portfolio.fit, and top cards per account/sleeve. Consults
blocked_structures to skip exact whatIf-rejected repeats.
"""

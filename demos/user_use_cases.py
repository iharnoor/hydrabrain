"""User-facing use cases for gbrain (pgvector) vs HydraDB comparison demos.

Each case maps a real question a person would ask their second brain to a
benchmark row in bench/headtohead_results.json or bench/relational_results.json.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserUseCase:
    id: str
    title: str
    user_story: str
    question: str
    expected: str
    vector_problem: str  # why pgvector-style search struggles
    corpus: str  # "timeline" | "network"
    benchmark_question: str  # exact question in headtohead rows


TIMELINE_USE_CASES: list[UserUseCase] = [
    UserUseCase(
        id="trips-abroad",
        title="Plan your next vacation",
        user_story="You saved years of travel memories and want every out-of-state trip — not just Florida beach days.",
        question="What trips did we take that were NOT in Florida?",
        expected="Princeton/NJ (July 2021) and India/Taj Mahal (March 2022)",
        vector_problem="Vector search ranks Miami & FSU trips first — 'trip' similarity drowns out geography.",
        corpus="timeline",
        benchmark_question="What trips did Harnoor and Katie take that were NOT in Florida?",
    ),
    UserUseCase(
        id="international",
        title="Find your international moments",
        user_story="You're making a photo book and need every memory that happened outside the US.",
        question="Which events happened outside the United States?",
        expected="Only the India trip — visiting the Taj Mahal in March 2022",
        vector_problem="Any travel chunk scores similarly — pgvector can't filter by country entity.",
        corpus="timeline",
        benchmark_question="Which events happened outside of the United States?",
    ),
    UserUseCase(
        id="relationship-arc",
        title="Write your anniversary post",
        user_story="You want the full relationship story across months — first date → Valentine's → buying a car together.",
        question="How did our relationship progress from casual dating to major commitments?",
        expected="Car date Nov 2020 → Valentine's dinner Feb 2021 → Tesla together May 2022",
        vector_problem="Top-5 returns one milestone; misses the arc spanning 3+ separate memories.",
        corpus="timeline",
        benchmark_question="How did Harnoor and Katie's relationship progress from casual dating to major commitments?",
    ),
    UserUseCase(
        id="non-birthday",
        title="Plan a celebration (not a birthday)",
        user_story="You're planning a party and want past celebrations that weren't birthdays.",
        question="What did we celebrate together that was NOT a birthday?",
        expected="Navratri, July 4th, Valentine's, Thanksgiving, Christmas, New Year's, wedding",
        vector_problem="'Birthday' in the query pulls birthday chunks first — cosine can't negate.",
        corpus="timeline",
        benchmark_question="What did Harnoor and Katie celebrate together that was NOT a birthday?",
    ),
    UserUseCase(
        id="cross-cultural",
        title="Prepare to meet the family",
        user_story="You want to remember how you both embraced each other's cultures before a family visit.",
        question="How did we embrace each other's cultures?",
        expected="Katie: Navratri/lehenga, Indian clothing at Taj Mahal. Harnoor: Thanksgiving, Christmas.",
        vector_problem="Must combine 3+ memories; vector top-5 often returns only one cultural moment.",
        corpus="timeline",
        benchmark_question="How did Harnoor and Katie embrace each other's cultures?",
    ),
    UserUseCase(
        id="birthday-direction",
        title="Remember who did what",
        user_story="You want to recall what your partner did for YOUR birthday — not confuse it with theirs.",
        question="What did Katie specifically do for my birthday?",
        expected="Surprised him with a blue gift bag at his apartment, December 23, 2020",
        vector_problem="Both birthday memories score equally — vector can't tell Katie→you from you→Katie.",
        corpus="timeline",
        benchmark_question="What did Katie specifically do for Harnoor's birthday?",
    ),
]

NETWORK_USE_CASES: list[UserUseCase] = [
    UserUseCase(
        id="cap-table",
        title="Track your investor network",
        user_story="From meeting notes and CRM exports — who actually invested in a portfolio company?",
        question="Who invested in widget-co?",
        expected="alice, bob, fund-a",
        vector_problem="Relational 'who invested in X' needs typed edges — pure vector misses entity direction.",
        corpus="network",
        benchmark_question="who invested in widget-co",
    ),
    UserUseCase(
        id="team-map",
        title="Map your startup network",
        user_story="Before a intro email — who works at acme-co?",
        question="Who works at acme-co?",
        expected="dave, frank",
        vector_problem="Employment edges require graph traversal, not keyword similarity alone.",
        corpus="network",
        benchmark_question="who works at acme-co",
    ),
]

ALL_USE_CASES = TIMELINE_USE_CASES + NETWORK_USE_CASES

import math


def calculate_vote_weight(voter_karma: int) -> float:
    """Zero karma has 0 weight; reputation scales sub-linearly."""
    if voter_karma <= 0:
        return 0.0
    return math.sqrt(voter_karma)


def should_clarify(votes: list[tuple[int, int]]) -> bool:
    """
    Evaluates whether a claim qualifies for a Clarify badge.
    Each vote is a tuple of (value, voter_karma) where:
      - value: +1 (votes to clarify/flag) or -1 (validates original article/rejects claim)
      - voter_karma: integer score >= 0
    """
    ACTIVATION_WEIGHT_THRESHOLD = 8.0  # Combined affirmative weight required
    MINIMUM_REPUTABLE_VOTERS = 3       # Diversity requirement (cannot be triggered by 1-2 users)
    REPUTABLE_KARMA_CUTOFF = 5         # Established account threshold

    affirmative_weight = 0.0
    negative_weight = 0.0
    reputable_affirmative_voters = 0

    for value, karma in votes:
        weight = calculate_vote_weight(karma)

        if value > 0:
            affirmative_weight += weight
            if karma >= REPUTABLE_KARMA_CUTOFF:
                reputable_affirmative_voters += 1
        elif value < 0:
            negative_weight += weight

    # Rule 1: Must satisfy diversity threshold
    if reputable_affirmative_voters < MINIMUM_REPUTABLE_VOTERS:
        return False

    # Rule 2: Must satisfy net positive weight threshold
    net_weight = affirmative_weight - negative_weight
    if net_weight < ACTIVATION_WEIGHT_THRESHOLD:
        return False

    # Rule 3: Must maintain at least 65% affirmative consensus
    total_active_weight = affirmative_weight + negative_weight
    if total_active_weight == 0 or (affirmative_weight / total_active_weight) < 0.65:
        return False

    return True
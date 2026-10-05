import math

# Tunable thresholds
ACTIVATION_WEIGHT_THRESHOLD = 9.0  # Requires collective weight from multiple established accounts
MINIMUM_REPUTABLE_VOTERS = 3       # Diversity requirement (distinct reputable human accounts)
REPUTABLE_KARMA_CUTOFF = 5         # Cutoff for what constitutes an established voter
CONSENSUS_RATIO_THRESHOLD = 0.65   # Supermajority consensus requirement (65%)
MAX_VOTER_WEIGHT = 3.5             # Upper bound on any single voter's weight (caps whale dominance)


def calculate_vote_weight(voter_karma: int) -> float:
    """
    Zero karma yields 0.0 weight.
    Reputation scales sub-linearly and is capped at MAX_VOTER_WEIGHT to eliminate whale dominance.
    """
    if voter_karma <= 0:
        return 0.0
    raw_weight = math.sqrt(voter_karma)
    return min(raw_weight, MAX_VOTER_WEIGHT)


def should_clarify(votes: list[tuple[int, int]]) -> bool:
    """
    Evaluates whether a claim qualifies for a Clarify badge.
    Each vote is a tuple of (value, voter_karma).
    """
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

    # Rule 1: Diversity threshold (at least N distinct reputable voters)
    if reputable_affirmative_voters < MINIMUM_REPUTABLE_VOTERS:
        return False

    # Rule 2: Minimum collective weight threshold
    net_weight = affirmative_weight - negative_weight
    if net_weight < ACTIVATION_WEIGHT_THRESHOLD:
        return False

    # Rule 3: Supermajority agreement ratio
    total_active_weight = affirmative_weight + negative_weight
    if total_active_weight == 0 or (affirmative_weight / total_active_weight) < CONSENSUS_RATIO_THRESHOLD:
        return False

    return True
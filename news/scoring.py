import math
from django.db import transaction

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


def resolve_claim_if_ready(claim) -> bool:
    """
    Evaluates whether a claim qualifies for resolution using row-level locking.
    Runs inside a single atomic transaction.
    Returns True ONLY if this specific invocation transitioned the claim to resolved.
    Returns False if the claim was already resolved or consensus was not met.
    """
    from news.models import ClarificationClaim, Article

    with transaction.atomic():
        locked_claim = (
            ClarificationClaim.objects
            .select_for_update()
            .select_related("article")
            .get(id=claim.id)
        )

        # 1. Early exit: already resolved, so nothing newly resolved on this call
        if locked_claim.is_active_badge:
            return False

        # 2. Extract (value, voter_karma) from current votes
        votes_data = list(
            locked_claim.votes.values_list("value", "user__karma")
        )

        # 3. Evaluate consensus
        if should_clarify(votes_data):
            locked_claim.is_active_badge = True
            locked_claim.save(update_fields=["is_active_badge"])
            claim.is_active_badge = True

            article = locked_claim.article
            if article.clarify_status != Article.ClarifyStatus.CLARIFIED:
                article.clarify_status = Article.ClarifyStatus.CLARIFIED
                article.save(update_fields=["clarify_status"])

            return True

        return False
import os
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from django.utils import timezone

logger = logging.getLogger(__name__)


class SportsProvider(ABC):
    """
    Abstract interface for Swappable Sports Data Providers.
    Allows seamlessly switching between external API feeds (API-Football, CricketData)
    and mock providers without altering controllers.
    """

    @abstractmethod
    def get_live_scores(self) -> List[Dict[str, Any]]:
        """Returns normalized list of live match scores."""
        pass


class MockSportsProvider(SportsProvider):
    """
    Realistic simulated sports score provider for development & testing.
    """

    def get_live_scores(self) -> List[Dict[str, Any]]:
        now_iso = timezone.now().isoformat()
        return [
            {
                "id": "cric_ind_aus_2026",
                "sport": "Cricket",
                "home": "India",
                "away": "Australia",
                "home_score": "184/3",
                "away_score": "142/6",
                "status": "LIVE",
                "overs_or_period": "16.4 overs",
                "overs/period": "16.4 overs",
                "venue": "Narendra Modi Stadium, Ahmedabad",
                "tournament": "ICC Men's T20 Championship",
                "updated_at": now_iso,
            },
            {
                "id": "foot_ars_mci_2026",
                "sport": "Football",
                "home": "Arsenal",
                "away": "Manchester City",
                "home_score": "2",
                "away_score": "1",
                "status": "LIVE",
                "overs_or_period": "76'",
                "overs/period": "76'",
                "venue": "Emirates Stadium, London",
                "tournament": "Premier League",
                "updated_at": now_iso,
            },
            {
                "id": "bball_lal_gsw_2026",
                "sport": "Basketball",
                "home": "LA Lakers",
                "away": "Golden State Warriors",
                "home_score": "98",
                "away_score": "95",
                "status": "LIVE",
                "overs_or_period": "Q4 3:15",
                "overs/period": "Q4 3:15",
                "venue": "Crypto.com Arena, Los Angeles",
                "tournament": "NBA Regular Season",
                "updated_at": now_iso,
            },
            {
                "id": "ten_alc_sin_2026",
                "sport": "Tennis",
                "home": "Carlos Alcaraz",
                "away": "Jannik Sinner",
                "home_score": "6-4, 4-6, 3-2",
                "away_score": "4-6, 6-4, 2-3",
                "status": "LIVE",
                "overs_or_period": "Set 3 • Game 6",
                "overs/period": "Set 3 • Game 6",
                "venue": "Centre Court, Wimbledon",
                "tournament": "ATP Masters",
                "updated_at": now_iso,
            },
        ]


class ApiSportsProvider(SportsProvider):
    """
    Live API Sports Provider reading SPORTS_API_KEY from environment.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_live_scores(self) -> List[Dict[str, Any]]:
        import requests
        try:
            # Query external API (API-Sports / SportsDataIO)
            headers = {"x-apisports-key": self.api_key, "Accept": "application/json"}
            resp = requests.get(
                "https://v3.football.api-sports.io/fixtures?live=all",
                headers=headers,
                timeout=4
            )
            if resp.status_code == 200:
                data = resp.json().get("response", [])
                results = []
                now_iso = timezone.now().isoformat()
                for item in data[:8]:
                    teams = item.get("teams", {})
                    goals = item.get("goals", {})
                    fixture = item.get("fixture", {})
                    status_obj = fixture.get("status", {})

                    results.append({
                        "id": f"api_{fixture.get('id')}",
                        "sport": "Football",
                        "home": teams.get("home", {}).get("name", "Home"),
                        "away": teams.get("away", {}).get("name", "Away"),
                        "home_score": str(goals.get("home") if goals.get("home") is not None else 0),
                        "away_score": str(goals.get("away") if goals.get("away") is not None else 0),
                        "status": status_obj.get("short", "LIVE"),
                        "overs_or_period": f"{status_obj.get('elapsed', 0)}'",
                        "overs/period": f"{status_obj.get('elapsed', 0)}'",
                        "updated_at": now_iso,
                    })
                if results:
                    return results
        except Exception as e:
            logger.warning(f"[ApiSportsProvider] API fetch failed: {e}. Falling back to mock data.")

        return MockSportsProvider().get_live_scores()


def get_sports_provider() -> SportsProvider:
    """Factory selecting live or mock provider based on environment configuration."""
    api_key = os.getenv("SPORTS_API_KEY", "").strip()
    if api_key:
        return ApiSportsProvider(api_key=api_key)
    return MockSportsProvider()

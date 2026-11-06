import re
import secrets

from django.conf import settings
from django.db.models import BooleanField, F, Func, Q

COUNTRY = re.compile(r"[A-Z]{2}")


def normalize_policy(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"mode", "countries"}:
        raise ValueError("region restriction must contain mode and countries")
    mode, countries = value["mode"], value["countries"]
    if mode not in ("allowed", "blocked", "unrestricted") or not isinstance(countries, list):
        raise ValueError("invalid region restriction")
    if any(not isinstance(code, str) or not COUNTRY.fullmatch(code) or code in ("XX", "T1") for code in countries):
        raise ValueError("invalid country code")
    if mode == "unrestricted" and countries:
        raise ValueError("unrestricted policy cannot contain countries")
    return {"mode": mode, "countries": sorted(set(countries))}


def policy_from_item(item):
    if item is None:
        return None
    restriction = item["contentDetails"].get("regionRestriction")
    if restriction is None:
        return {"mode": "unrestricted", "countries": []}
    if (
        not isinstance(restriction, dict)
        or len(restriction) != 1
        or next(iter(restriction)) not in ("allowed", "blocked")
    ):
        raise ValueError("invalid YouTube region restriction")
    mode = next(iter(restriction))
    return normalize_policy({"mode": mode, "countries": restriction[mode]})


def viewer_country(request):
    if request is None:
        return None
    token = settings.VIEWER_CONTEXT_TOKEN
    supplied = request.headers.get("X-Viewer-Context-Token", "")
    if not token or not secrets.compare_digest(supplied, token):
        return None
    country = request.headers.get("X-Viewer-Country", "")
    return country if COUNTRY.fullmatch(country) and country not in ("XX", "T1") else None


def availability(song, country):
    reason = song.youtube_unplayable_reason
    status = "blocked" if reason or not song.youtube_video_id else "unknown"
    if status != "blocked" and (policy := song.youtube_region_restriction) is not None:
        mode, countries = policy["mode"], policy["countries"]
        if mode == "unrestricted" or (mode == "blocked" and not countries):
            status = "eligible"
        elif mode == "allowed" and not countries:
            status, reason = "blocked", "region_blocked"
        elif country is not None:
            blocked = (country not in countries) if mode == "allowed" else (country in countries)
            status, reason = ("blocked", "region_blocked") if blocked else ("eligible", None)
    return {"status": status, "reason": reason, "country": country}


class RegionBlocked(Func):
    output_field = BooleanField()

    def __init__(self, country):
        super().__init__(F("youtube_region_restriction"))
        self.country = country

    def as_sql(self, compiler, connection, **extra_context):
        policy, params = compiler.compile(self.source_expressions[0])
        if connection.vendor == "postgresql":
            predicate, country_params = _blocked_sql(policy, self.country)
            return f"coalesce(({predicate}), false)", [*params, *country_params]
        if connection.vendor != "sqlite":
            raise NotImplementedError("regional policies require PostgreSQL or SQLite")
        mode = f"json_extract({policy}, '$.mode')"
        countries = f"json_extract({policy}, '$.countries')"
        predicate = f"({mode} = 'allowed' AND json_array_length({countries}) = 0)"
        if self.country is not None:
            contains = f"EXISTS (SELECT 1 FROM json_each({countries}) WHERE value = %s)"
            predicate += f" OR ({mode} = 'allowed' AND NOT {contains}) OR ({mode} = 'blocked' AND {contains})"
            params = [*params, self.country, self.country]
        return f"coalesce(({predicate}), false)", params


def _blocked_sql(policy, country):
    blocked = f"({policy}->>'mode' = 'allowed' AND {policy}->'countries' = '[]'::jsonb)"
    params = []
    if country is not None:
        blocked += f" OR ({policy}->>'mode' = 'allowed' AND NOT ({policy}->'countries' ? %s))"
        blocked += f" OR ({policy}->>'mode' = 'blocked' AND {policy}->'countries' ? %s)"
        params = [country, country]
    return blocked, params


def attemptable(country):
    """Song queryset predicate; unknown country/metadata permits an attempt."""
    from grow.model.song.playable import PLAYABLE

    return PLAYABLE & Q(_region_blocked=False)


def with_region_status(queryset, country):
    return queryset.alias(_region_blocked=RegionBlocked(country))


def attemptable_sql(country):
    blocked, _ = _blocked_sql("s.youtube_region_restriction", country)
    blocked = blocked.replace("%s", "%(country)s")
    return (
        f"s.youtube_video_id IS NOT NULL AND s.youtube_unplayable_reason IS NULL AND NOT coalesce(({blocked}), false)",
        {"country": country} if country is not None else {},
    )

"""Collect Berlin property managers from OpenStreetMap (ODbL: attribution required)."""

import logging
from datetime import UTC, datetime

import requests

from pipeline import config
from pipeline.models import Company, SourceRef
from pipeline.utils.http import HttpClient
from pipeline.utils.io import write_raw
from pipeline.utils.urls import company_id, normalize_url

log = logging.getLogger(__name__)

SOURCE = "osm"


def collect_osm(client: HttpClient) -> list[Company]:
    payload = _fetch_overpass(client)
    raw_path = write_raw(config.RAW_DIR, SOURCE, payload)
    collected_at = datetime.now(UTC)
    companies = [c for el in payload["elements"] if (c := _to_company(el, collected_at))]
    with_site = sum(1 for c in companies if c.website)
    log.info("OSM: %d companies (%d with website), raw: %s", len(companies), with_site, raw_path)
    return companies


def _build_query() -> str:
    return f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT_SECONDS}];
area["name"="Berlin"]["admin_level"="4"]->.b;
(
  nwr(area.b)["office"="property_management"];
  nwr(area.b)["name"~"{config.OVERPASS_NAME_PATTERN}",i];
);
out tags center;
"""


def _fetch_overpass(client: HttpClient) -> dict:
    query = _build_query()
    for url in config.OVERPASS_MIRRORS:
        try:
            resp = client.post(url, data={"data": query}, timeout=config.OVERPASS_TIMEOUT_SECONDS)
            log.info("Overpass OK via %s", url)
            return resp.json()
        except requests.RequestException as e:
            log.warning("Overpass mirror failed (%s): %s", url, e)
    raise RuntimeError("All Overpass mirrors failed")


def _to_company(el: dict, collected_at: datetime) -> Company | None:
    tags = el.get("tags", {})
    if not tags.get("name"):
        return None
    osm_id = f"{el['type']}/{el['id']}"
    website = normalize_url(_first_value(tags, "website", "contact:website", "url"))
    return Company(
        id=company_id(website, SOURCE, osm_id),
        name=tags["name"],
        website=website,
        phone=_first_value(tags, "phone", "contact:phone"),
        email_general=_first_value(tags, "email", "contact:email"),
        street=" ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))
        or None,
        postcode=tags.get("addr:postcode"),
        city=tags.get("addr:city"),
        sources=[
            SourceRef(
                source=SOURCE,
                source_id=osm_id,
                url=f"https://www.openstreetmap.org/{osm_id}",
                collected_at=collected_at,
            )
        ],
    )


def _first_value(tags: dict, *keys: str) -> str | None:
    """OSM allows several values separated by ';' — take the first non-empty one."""
    for key in keys:
        if value := tags.get(key):
            return value.split(";")[0].strip() or None
    return None

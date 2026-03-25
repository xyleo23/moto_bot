"""Yandex Maps deep links (SOS, events).

Mobile Yandex Maps often needs both ``ll`` (map center) and ``pt`` (marker);
``pt`` alone can open an imprecise area view in the app while Navigator
handles the same URL differently.
"""


def yandex_maps_point_url(lat: float, lon: float, *, zoom: int = 18) -> str:
    """
    Open Yandex Maps at a precise point with a placemark.

    Yandex expects ``ll`` and ``pt`` as longitude,latitude.
    """
    lon_s = f"{float(lon):.7f}".rstrip("0").rstrip(".")
    lat_s = f"{float(lat):.7f}".rstrip("0").rstrip(".")
    return (
        f"https://yandex.ru/maps/?ll={lon_s},{lat_s}"
        f"&pt={lon_s},{lat_s}&z={int(zoom)}&l=map"
    )


def yandex_maps_href_for_html(lat: float, lon: float, *, zoom: int = 18) -> str:
    """``href`` value for Telegram/MAX HTML messages (escape ``&``)."""
    return yandex_maps_point_url(lat, lon, zoom=zoom).replace("&", "&amp;")


def is_plausible_gps_coordinate(lat: float, lon: float) -> bool:
    """False for null island and out-of-range values (bad client/API payloads)."""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    if lat == 0.0 and lon == 0.0:
        return False
    return True


def format_sos_broadcast_map_html(lat: float, lon: float) -> str:
    """Suffix for SOS broadcast body (Telegram/MAX HTML)."""
    from src import texts

    return texts.SOS_BROADCAST_MAP.format(
        lat=lat,
        lon=lon,
        href=yandex_maps_href_for_html(lat, lon),
        link_label=texts.SOS_BROADCAST_MAP_LINK_LABEL,
    )

"""Validated orbital cache and offline solar elevation for point predictions."""

import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import ephem
except ImportError:
    ephem = None


def tle_epoch(tle, norad_id):
    """Validate a numeric NORAD TLE and return its UTC epoch."""
    if len(tle) != 2:
        raise ValueError('Expected two TLE lines')
    for number, line in enumerate(tle, start=1):
        if len(line) != 69 or not line.startswith(f'{number} '):
            raise ValueError('Invalid TLE format')
        if int(line[2:7]) != int(norad_id):
            raise ValueError('TLE NORAD identity mismatch')
        checksum = sum(int(char) if char.isdigit() else int(char == '-') for char in line[:68])
        if checksum % 10 != int(line[68]):
            raise ValueError('Invalid TLE checksum')
    year = int(tle[0][18:20])
    year += 1900 if year >= 57 else 2000
    day = float(tle[0][20:32])
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    if not 1 <= day < (datetime(year + 1, 1, 1, tzinfo=timezone.utc) - start).days + 1:
        raise ValueError('Invalid TLE epoch')
    return start + timedelta(days=day - 1)


class TleCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def read(self, norad_id):
        try:
            record = json.loads((self.directory / f'{int(norad_id)}.json').read_text(encoding='utf-8'))
            tle = tuple(record['tle'])
            epoch = tle_epoch(tle, norad_id)
            fetched = datetime.fromisoformat(record['fetched_at'])
            if fetched.utcoffset() is None:
                return None
            return dict(tle=tle, epoch=epoch, fetched_at=fetched, source='cache')
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return None

    def write(self, norad_id, tle, fetched_at):
        epoch = tle_epoch(tle, norad_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             suffix='.tmp', delete=False) as handle:
                temporary = handle.name
                json.dump(dict(tle=list(tle), fetched_at=fetched_at.isoformat()), handle)
            os.replace(temporary, self.directory / f'{int(norad_id)}.json')
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return dict(tle=tuple(tle), epoch=epoch, fetched_at=fetched_at, source='network')


def solar_elevation(lat, lon, instant):
    """Geometric topocentric solar altitude, without atmospheric refraction."""
    if ephem is None:
        raise RuntimeError('PyEphem unavailable: optical prediction not available')
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    observer.elevation = 0
    observer.pressure = 0
    observer.date = instant.astimezone(timezone.utc).replace(tzinfo=None)
    return math.degrees(float(ephem.Sun(observer).alt))


def prediction_window(start_day, end_day, now, hours=48, use_dates=False):
    start = max(now, datetime(start_day.year, start_day.month, start_day.day, tzinfo=timezone.utc))
    if use_dates:
        end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc) + timedelta(days=1)
    else:
        end = start + timedelta(hours=hours)
    if end <= start:
        raise ValueError('Prediction end must follow start')
    return start, end


def geodetic_ecef(lat, lon):
    latitude = math.radians(lat)
    longitude = math.radians(lon)
    eccentricity_sq = 6.69437999014e-3
    radius = 6378.137 / math.sqrt(1 - eccentricity_sq * math.sin(latitude) ** 2)
    return (radius * math.cos(latitude) * math.cos(longitude),
            radius * math.cos(latitude) * math.sin(longitude),
            radius * (1 - eccentricity_sq) * math.sin(latitude))


def ecef_geodetic(position):
    east, north, vertical = position
    horizontal = math.hypot(east, north)
    longitude = math.atan2(north, east)
    eccentricity_sq = 6.69437999014e-3
    latitude = math.atan2(vertical, horizontal * (1 - eccentricity_sq))
    for iteration in range(8):
        radius = 6378.137 / math.sqrt(1 - eccentricity_sq * math.sin(latitude) ** 2)
        latitude = math.atan2(vertical + eccentricity_sq * radius * math.sin(latitude), horizontal)
    altitude = (horizontal * math.cos(latitude) + vertical * math.sin(latitude)
                - 6378.137 * math.sqrt(1 - eccentricity_sq * math.sin(latitude) ** 2))
    return math.degrees(latitude), math.degrees(longitude), altitude
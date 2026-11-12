"""Satellite parameter overrides derived from developmentseed/eo-predictor.

Source reference:
https://github.com/developmentseed/eo-predictor/tree/main/scripts/satellites

Values here are intentionally limited to metadata useful for overpass
prediction in Smart Tasking.
"""

EO_PREDICTOR_SATELLITE_OVERRIDES = {
    'worldview-3': {
        'altitude_km': 617,
        'swath_km': 13,
        'off_nadir_deg': 30,
        'norad_ids': [40115],
    },
    'worldview-2': {
        'altitude_km': 770,
        'swath_km': 16,
        'off_nadir_deg': 30,
        'norad_ids': [35946],
    },
    'worldview-legion': {
        'altitude_km': 521,
        'swath_km': 10,
        'off_nadir_deg': 30,
        'norad_ids': [59625, 59626, 60452, 60453, 62900, 62901],
    },
    'skysat': {
        'altitude_km': 475,
        'swath_km': 6,
        'off_nadir_deg': 45,
        'norad_ids': [
            39418, 40072, 41601, 41771, 41772, 41773, 41774,
            42987, 42988, 42989, 42990, 42991, 42992, 43797, 43802,
        ],
    },
    'planetscope': {
        'altitude_km': 525,
        'swath_km': 8,
        'off_nadir_deg': 0,
        'norad_ids': [
            58270, 58271, 58273, 58274, 58275, 58280, 58282, 58283,
            58284, 58285, 58286, 58303, 58304, 58306, 58307, 58308,
            58309, 58313, 58316, 58318, 58319, 58320, 58322, 58327,
            58328, 58329, 60480, 60481, 60483, 60484, 60486, 60487,
            60488, 60489, 60490, 60491, 60492, 60494, 60495, 60497,
            60499, 60501, 60502, 60503, 60505, 60509, 60511, 60512,
            60513, 60514, 60515, 60516, 60517, 60518, 60519, 60558,
            60559, 60560, 60561, 60563,
        ],
    },
    'iceye': {
        'altitude_km': 580,
        'swath_km': 5,
        'off_nadir_deg': 40,
        'norad_ids': [
            43800, 44389, 44390, 46496, 46497, 48918, 55049, 56947,
            56961, 56963, 58288, 58294, 58302, 59100, 59102, 59103,
            60539, 60546, 60548, 60549, 62384, 62389, 62698, 62700,
            62705, 62707,
        ],
    },
    'sentinel-1': {
        'altitude_km': 693,
        'swath_km': 410,
        'off_nadir_deg': 33,
        'norad_ids': [39634, 62261],
    },
    'sentinel-2': {
        'altitude_km': 786,
        'swath_km': 290,
        'off_nadir_deg': 0,
        'norad_ids': [40697, 42063, 60989],
    },
    'landsat': {
        'altitude_km': 705,
        'swath_km': 185,
        'off_nadir_deg': 0,
        'norad_ids': [39084, 49260],
    },
    'nisar': {
        'altitude_km': 747,
        'swath_km': 240,
        'off_nadir_deg': 37,
        'norad_ids': [65053],
    },
}

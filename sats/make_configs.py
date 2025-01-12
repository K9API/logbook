from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from functools import total_ordering
from io import StringIO
import logging
from math import nan
from pathlib import Path
from typing import Self
import pandas
import requests_cache
from xdg_base_dirs import xdg_config_home


FREQUENCY_COLUMNS = ["uplink", "downlink", "beacon"]
DEFAULT_QTH = "Home.qth"

# TODO: check this on windows
GPREDICT_CONFIG_DIR = xdg_config_home() / "Gpredict"
GPREDICT_MODULE_DEST = GPREDICT_CONFIG_DIR / "modules"


def is_2m(freq):
    return (144 <= freq) & (freq <= 148)


def is_70cm(freq):
    return (420 <= freq) & (freq <= 450)


def is_vu(freq):
    return is_2m(freq) | is_70cm(freq)


@dataclass(frozen=True)
class FrequencyRange:
    start: float
    stop: float

    # Custom comparison operators for if the range is inside a frequency band

    def __le__(self, freq: float):
        return self.start <= freq and self.stop <= freq

    def __ge__(self, freq: float):
        return self.start >= freq and self.stop >= freq


def active_frequency(cell) -> float | FrequencyRange:
    cell = str(cell)

    if "-" in cell:
        # Frequency range (e.g. SSB transponder?)
        a, _sep, b = cell.partition("-")
        try:
            return FrequencyRange(float(a), float(b))
        except ValueError:
            logging.warning("Unable to parse frequency: %r, ignoring", cell)
            return nan

    options = str(cell).split("/")
    if len(options) == 1:
        selection = options[0].removesuffix("*")
    else:
        selection = next((o.removesuffix("*") for o in options if o.endswith("*")), nan)

    try:
        return float(selection)
    except ValueError:
        logging.warning("Unable to parse frequency: %r, ignoring", selection)
        return nan


def get_active_satellites() -> pandas.DataFrame:
    session = requests_cache.CachedSession(
        expire_after=timedelta(days=1),
    )
    session.headers["User-Agent"] = (
        "make_configs (adam@gaussian.dev;https://github.com/K9API/logbook)"
    )

    amsat_csv = session.get(
        "https://raw.githubusercontent.com/palewire/amateur-satellite-database/refs/heads/main/data/amsat-all-frequencies.csv"
    )
    amsat_csv.raise_for_status()
    amsat_db = pandas.read_csv(StringIO(amsat_csv.text))

    for c in FREQUENCY_COLUMNS:
        amsat_db[c] = amsat_db[c].map(active_frequency)

    satnogs_csv = session.get(
        "https://raw.githubusercontent.com/palewire/amateur-satellite-database/refs/heads/main/data/satnogs.csv"
    )
    satnogs_csv.raise_for_status()
    satnogs_db = pandas.read_csv(StringIO(satnogs_csv.text))

    satnogs_alive_ids = set(satnogs_db.sat_id.where(satnogs_db.status == "alive"))
    any_frequency_listed = amsat_db[FREQUENCY_COLUMNS].notna().any(axis="columns")

    return amsat_db[
        amsat_db.status.isin(["active", "operational"])
        & amsat_db.satnogs_id.isin(satnogs_alive_ids)
        & any_frequency_listed
    ]


def make_gpredict_module(satellite_ids: Iterable) -> str:
    satellites = ";".join(str(int(i)) for i in satellite_ids)
    return f"""[GLOBAL]\nSATELLITES={satellites}\nQTHFILE={DEFAULT_QTH}\n"""


def save_gpredict_module(name: str, dest_dir: Path, satellite_ids: Iterable):
    with (dest_dir / f"{name}.mod").open("w+") as f:
        f.write(make_gpredict_module(satellite_ids))


def main():
    logging.basicConfig(level=logging.INFO)
    pandas.set_option("future.no_silent_downcasting", True)

    active_db = get_active_satellites()

    all_beacons = active_db[is_vu(active_db.beacon)]
    save_gpredict_module(
        "AMSAT_All_Beacons",
        GPREDICT_MODULE_DEST,
        all_beacons.norad_id.drop_duplicates().dropna(),
    )

    all_fm = active_db[active_db["mode"].str.contains("FM").fillna(False)]
    save_gpredict_module(
        "AMSAT_All_Repeaters",
        GPREDICT_MODULE_DEST,
        all_fm.norad_id.drop_duplicates().dropna(),
    )

    all_digi = active_db[
        active_db["mode"].str.contains("APRS").fillna(False)
        | active_db["mode"].str.contains("Digipeater").fillna(False)
    ]
    save_gpredict_module(
        "AMSAT_All_Digi",
        GPREDICT_MODULE_DEST,
        all_digi.norad_id.drop_duplicates().dropna(),
    )


if __name__ == "__main__":
    main()

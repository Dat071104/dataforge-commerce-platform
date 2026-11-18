"""Fault mutations derived from the captured seven-date landing slice."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def mutate_landing_frame(fault_id: str, clean_frame: pd.DataFrame) -> pd.DataFrame:
    frame = clean_frame.copy(deep=True)
    first_date = frame["observation_date"].iloc[0]
    date_index = frame.index[frame["observation_date"] == first_date].tolist()

    if fault_id == "F01":
        frame.loc[frame.index[0], "province_id"] = None
    elif fault_id == "F02":
        duplicate = frame.loc[[date_index[0]]].copy()
        frame = frame.drop(index=date_index[-1])
        frame = pd.concat([frame, duplicate], ignore_index=True)
    elif fault_id == "F03":
        frame.loc[frame.index[0], "temp_max_c"] = 99.0
        frame.loc[frame.index[0], "precipitation_mm"] = -5.0
    elif fault_id == "F04":
        frame.loc[frame.index[0], "province_id"] = "SG"
    elif fault_id == "F05a":
        frame = frame.drop(columns=["model"])
    elif fault_id == "F05b":
        frame["new_nullable_field"] = None
    elif fault_id == "F06":
        frame = frame.drop(index=date_index[0]).reset_index(drop=True)
    elif fault_id == "F08":
        future_date = date.today() + timedelta(days=2)
        frame.loc[frame["observation_date"] == first_date, "observation_date"] = future_date
    elif fault_id == "F12":
        frame.loc[frame.index[0], "temp_max_c"] = 90.0
    elif fault_id in {"F-N0", "F09"}:
        pass
    else:
        raise ValueError(f"fault {fault_id} is not a landing-frame mutation")
    return frame

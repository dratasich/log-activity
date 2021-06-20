from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from dateutil.tz import tzlocal

from models.working_hours import WorkingHours


class WorkingTimeWriter:

    def __init__(self, df: pd.DataFrame):
        self.logs = df[["active", "lunch_incl", "start", "end"]].copy()
        self.logs.columns = [g[0] for g in self.logs.columns]
        self.logs["verification"] = self.logs.apply(WorkingTimeWriter._verify_row, axis=1)

    def _verify_row(row):
        """Returns notification for user on requirements' violation
        given a working time entry of a day."""
        # collection of user notifications
        notes = []
        isotoday = row["start"].date().isoformat()
        weekday = row["start"].isoweekday()

        # active time over 10.5 hours
        if row["active"] > timedelta(hours=10, minutes=30):
            notes.append("overtime (stay below <=10.5 hours)")

        # Kernzeit
        start_max, end_min = (
            datetime.fromisoformat(f"{isotoday}T09:00:00").astimezone(tz=tzlocal()),
            datetime.fromisoformat(f"{isotoday}T15:00:00").astimezone(tz=tzlocal()),
        )
        if weekday == 5:  # Fri min is 09:00 - 12:00
            end_min = datetime.fromisoformat(f"{isotoday}T12:00:00").astimezone(
                tz=tzlocal()
            )
        if weekday <= 5 and (row["start"] > start_max or row["end"] < end_min):
            notes.append(f"Kernzeit violation ({start_max.strftime('%H:%M')}-{end_min.strftime('%H:%M')})")

        # rest time
        start_min, end_max = (
            datetime.fromisoformat(f"{isotoday}T06:00:00").astimezone(tz=tzlocal()),
            datetime.fromisoformat(f"{isotoday}T19:00:00").astimezone(tz=tzlocal()),
        )
        if row["start"] < start_min:
            notes.append(f"rest time violation (work time >= {start_min.strftime('%H:%M')})")
        if row["end"] > end_max:
            notes.append(f"rest time violation (work time <= {end_max.strftime('%H:%M')})")

        # logs on weekends
        if (weekday == 6 or weekday == 7) and row["active"].seconds > 0:
            notes.append("logged time on weekend")

        # mismatching active time and end - start
        if row["end"] - row["start"] != row["active"]:
            notes.append("end - start != active")

        return ";".join(notes)

    def save(self):
        # format output for csv
        self.logs["start"] = self.logs["start"].apply(lambda r: WorkingHours.str_time(r))
        self.logs["end"] = self.logs["end"].apply(lambda r: WorkingHours.str_time(r))
        self.logs["active"] = self.logs["active"].apply(lambda r: WorkingHours.str_delta(r))
        # write to file
        self.logs.to_csv("working_time.csv")

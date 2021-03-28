import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple

import pandas as pd


class Activities():

    def __init__(self):
        self._activities = pd.DataFrame(columns=["project", "date", "time", "desc"]).set_index("project")

    def add(
            self,
            project: str,
            date: datetime,
            time: timedelta = timedelta(seconds=0),
            desc: str = "",
    ):
        self._activities = self._activities.append(
            {
                "project": project,
                "date": date,
                "time": time,
                "desc": desc,
            },
            ignore_index=True,
        )

    def __str__(self):
        return str(self._activities)

    def fill(self, working_hours: Dict[datetime, float]):
        raise RuntimeError("not yet implemented")

    def aggregate(self, date_range: Tuple[datetime, datetime] = None):
        # filter for specified range
        if date_range is None:
            a = self._activities
        else:
            a = self._activities[(self._activities.date >= date_range[0])
                                 & (self._activities.date <= date_range[1])]
        # aggregate
        return a.groupby(["date", "project"]).agg(
            {
                "time": sum,
                "desc": ";".join
            }
        )

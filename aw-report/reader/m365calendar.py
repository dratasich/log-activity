import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd


class M365CalendarReader():

    def __init__(self, filename: str):
        self._logger = logging.getLogger(__name__)
        self.events = self.__read(filename)

    def __read(self, filename: str):
        # load calendar
        try:
            calendar = pd.read_json(filename, orient="records")
        except:
            self._logger.warning("failed to read meetings")
            return None
        # filter columns
        calendar = calendar[
            ["subject", "startWithTimeZone", "endWithTimeZone", "categories"]
        ]
        # explode and filter categories (if len(categories) > 1, take only one)
        calendar = (
            calendar.explode("categories")
            .dropna()
            .drop_duplicates(["subject", "startWithTimeZone", "endWithTimeZone"])
        )
        # drop private events
        calendar = calendar[calendar["categories"] != "privat"]
        # calculate event duration
        calendar = calendar.astype(
            {"startWithTimeZone": "datetime64[ns, Europe/Vienna]", "endWithTimeZone": "datetime64[ns, Europe/Vienna]"}
        )
        calendar["duration"] = calendar["endWithTimeZone"] - calendar["startWithTimeZone"]
        # add date column for grouping per day
        calendar["date"] = calendar["startWithTimeZone"].dt.floor("d")
        return calendar

    def events_from(self, date):
        # meetings
        if self.events is None:
            return
        try:
            return self.events[self.events.date == pd.to_datetime(date).floor("d")]
        except KeyError as e:
            logger.debug(f"no events on this day")

    def events_within(self, date):
        # meetings
        if self.events is None:
            return
        else:
            return self.events[(self.events.date >= pd.to_datetime(date[0]).floor("d"))
                               & (self.events.date <= pd.to_datetime(date[1]).floor("d"))]

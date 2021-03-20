import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple

from dateutil.tz import tzlocal


class WorkingHours():

    def __init__(
            self,
            actual_start: datetime,
            actual_end: datetime,
            active: timedelta,
    ):
        self._logger = logging.getLogger(__name__)
        self.lunch_incl = False
        self.hours = self._align_hours(active)
        self.start, self.end = self._align_range(actual_start, actual_end, self.hours)

    def _align_hours(self, active: timedelta):
        # consider lunch break (a must when time >= 6h)
        working_hours = active
        working_hours_incl_lunch = working_hours
        if active >= timedelta(hours=6):
            self._logger.debug(f"add 30min break")
            working_hours_incl_lunch += timedelta(minutes=30)
            self.lunch_incl = True
        # round to 15min
        working_hours = self._round_timedelta(working_hours)
        working_hours_incl_lunch = self._round_timedelta(working_hours_incl_lunch)
        return working_hours_incl_lunch

    def _align_range(self, actual_start: datetime, actual_end: datetime, active: timedelta):
        """Converts start and end of today to something that is allowed and reflects active time."""
        weekday = actual_start.isoweekday()
        # ignore Kernzeit on weekends
        if weekday == 6 or weekday == 7:
            self._logger.debug(f"ignore Kernzeit as it is {actual_start.strftime('%A')}")
            return actual_start, actual_start + active

        # Kernzeit
        # Mon-Thu min is 09:00 - 15:00
        isotoday = actual_start.date().isoformat()
        start_max, end_min = (
            datetime.fromisoformat(f"{isotoday}T09:00:00").astimezone(tz=tzlocal()),
            datetime.fromisoformat(f"{isotoday}T15:00:00").astimezone(tz=tzlocal()),
        )
        if weekday == 5:  # Fri min is 09:00 - 12:00
            end_min = datetime.fromisoformat(f"{isotoday}T12:00:00").astimezone(
                tz=tzlocal()
            )

        if actual_start <= start_max and actual_start + active >= end_min:
            # actual timings within Kernzeit
            return actual_start, actual_start + active
        elif active < end_min - start_max:
            # worked not enough today
            self._logger.warning(
                f"Kernzeit-Violation ({self._str_time(actual_start)} - {self._str_time(actual_end)}, active={self._str_delta(active)})"
            )
            return start_max, start_max + active
        elif actual_start > start_max:
            # worked enough but started late, so shift start to the left ;)
            return start_max, start_max + active
        else:
            self._logger.warning(
                f"missed a case ({self._str_time(actual_start)} - {self._str_time(actual_end)}, active={self._str_delta(active)})"
            )
            return end_min - active, end_min

    def _round_timedelta(self, tm: timedelta, round_to_s=timedelta(minutes=15).total_seconds()):
        tm_rounded = timedelta(
            seconds=int((tm.total_seconds() + round_to_s / 2) / (round_to_s)) * (round_to_s)
        )
        self._logger.debug(f"{round_to_s}s-rounded {tm} to {tm_rounded}")
        return tm_rounded

    def _str_time(self, date: datetime):
        if date is None:
            return "00:00"
        return date.astimezone(tz=tzlocal()).strftime("%H:%M")

    def _str_delta(self, time: timedelta):
        h = int(time.total_seconds() / 3600)
        m = int((time.total_seconds() % 3600) / 60)
        return f"{h:02}:{m:02}"

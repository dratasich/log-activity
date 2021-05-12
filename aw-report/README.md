Report
======

Reads events from buckets per day and prints:

- [x] start and end of first and last afk-event (login and shutdown)
- [x] active time (sum of not-afk durations)
  - [x] add afk < 5min (e.g., 5-10min per hour is ok)
  - [x] add 30min for lunch
  - [x] round to 0:15
        (add an option to distinguish between report and aw summary)
- [ ] distribute active time to aw projects
- [x] git issues and commits (aw-git-hooks events)
  - [x] duplicates of (git-repo, summary) are removed
    (may happen on `git commit ammend or reword`)
- [x] time spent in meetings
  - [x] read exported calendar (json created via MS Automate/Flow)
  - [ ] window events containing "MS Teams"
  - [ ] meetings watcher reading MS outlook calendars (ical or via selenium)
- [ ] pomodoro (project, summary)

Usage
-----

Print report by issue:
```bash
$ ./report.py -c issue
```

See `./report.py -h` for more options.

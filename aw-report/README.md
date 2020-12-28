Report
======

Reads events from buckets per day and prints:

- [x] start and end of first and last afk-event (login and shutdown)
- [x] active time (sum of not-afk durations)
- [x] git issues and commits (aw-git-hooks events)
- [ ] time spent in meetings (window events containing "MS Teams")


Usage
-----

Print report by issue:
```bash
$ ./report.py -c issue
```

See `./report.py -h` for more options.

#!/usr/bin/env python3

import argparse
import datetime
import os
import re
import subprocess
import textwrap


# arguments
desc = "List activities per date."
parser = argparse.ArgumentParser(description=desc)
parser.add_argument('-g', '--git', metavar="DIRECTORY", type=str,
                    help="""Directory including git repos to list commits
                    from.""")
parser.add_argument('-f', '--from', dest='date',
                    default=datetime.date.today().replace(day=1),
                    type=lambda d: datetime.datetime.strptime(d, '%Y-%m-%d'),
                    help=f"""Start date. Defaults to
                    {datetime.date.today().replace(day=1)}
                    (first day of the current month).""")
args = parser.parse_args()


def execute(cmd):
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
    return result.stdout.decode('utf-8')


def str_date(date):
    return date.strftime('%Y-%m-%d')


def parse_date(string):
    return datetime.datetime.strptime(string, '%Y-%m-%d')


if __name__ == '__main__':
    # initialize topics per date
    topics = {}
    day = args.date  # start with first day of the month
    one_day = datetime.timedelta(days=1)
    while day.month == args.date.month:
        topics[str_date(day)] = {'git': [], 'meetings': []}
        day = day + one_day

    # minutes
    # assumption:
    # - for each meeting a minutes file has been created in the repo 'minutes'
    # - the file is named like: yyyy-mm-dd[_topic].md
    if args.git is not None:
        # regex for meeting minutes files
        p = re.compile('(\d{4}-\d{2}-\d{2})_?([a-z,A-Z,-]*)\.md')
        # get filenames
        minutes = os.listdir(f"{args.git}/minutes")
        # parse filenames and/or read headline to retrieve meeting topic
        for fn in minutes:
            date = None
            topic = ""
            # parse the file name
            try:
                groups = p.match(fn).groups()
                # use the date from the filename
                date = parse_date(groups[0])
            except Exception:
                # skip this meeting minute if the regex fails
                continue
            # skip the minutes from other months
            if date.month != args.date.month:
                continue
            # prefer the description from the headline/first line of the file
            # use first line (headline) of the file as topic
            with open(f"{args.git}/minutes/" + fn) as f:
                topic = f.readline().strip()
            # use info in file name as topic
            if topic is None or topic == "" or len(topic) < 3:
                topic = groups[1]
            topics[str_date(date)]['meetings'].append(topic)

    # git commits
    if args.git is not None:
        # collects git commit messages in one line
        lines = []
        # regex for commit message's timestamp
        p = re.compile('^(\d{4}-\d{2}-\d{2})')
        # get list of directories
        dirs = os.listdir(args.git)
        for repo in dirs:
            # concatenate directory
            d = args.git + '/' + repo
            # get author name from git repo
            author = execute(f'cd {d}; git config user.name').strip()
            # print one line commits
            out = execute(f"""cd {d}; git log --date=iso --since={str_date(args.date)} --pretty=format:'%aI %s' --author='{author}'""") + "\n"
            commits = out.split('\n')
            for c in commits:
                try:
                    # parse
                    iso_date, message = c.split(' ', maxsplit=1)
                    groups = p.match(iso_date).groups()
                    date = groups[0]
                except Exception:
                    # skip if the regex fails
                    continue
                # skip commits with wrong month
                if parse_date(date).month != args.date.month:
                    continue
                # skip insufficient commit messages
                if message is None or message == "" or len(message) < 3:
                    continue
                topics[date]['git'].append(f"{repo}: {message}")

    # output
    for k, v in topics.items():
        # skip weekend
        date = parse_date(k)
        weekday = date.weekday()
        if weekday >= 5:
            continue
        # new week formatting
        if weekday == 0:
            print("{:-^80}".format(f" Week {date.isocalendar()[1]} "))
        # formatted output
        print(f"{k}: Meetings: {', '.join(v['meetings'])}\n"
              + textwrap.indent('\n'.join(v['git']), "  "))

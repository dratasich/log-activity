#!/usr/bin/env python3

import argparse
import datetime
import os
import subprocess


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


if __name__ == '__main__':
    lines = []

    # git commits
    if args.git is not None:
        # get list of directories
        dirs = list(map(lambda d: args.git + d, os.listdir(args.git)))
        out = ""
        for d in dirs:
            # get author name from git repo
            author = execute(f'cd {d}; git config user.name').strip()
            # print one line commits
            out += execute(f"""cd {d}; git log --date=iso --since={str_date(args.date)} --pretty=format:'%ad: %s' --author='{author}'""") + "\n"
        lines.extend(out.split('\n'))

    # cleanup
    lines = list(map(lambda l: l.strip(), lines))
    while True:
        try:
            # blank lines
            lines.remove('')
        except ValueError:
            break

    # sort and print
    print('\n'.join(sorted(lines)))

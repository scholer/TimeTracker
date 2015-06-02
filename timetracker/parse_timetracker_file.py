#!/usr/bin/env python3
# -*- coding: utf-8 -*-
##    Copyright 2015 Rasmus Scholer Sorensen, rasmusscholer@gmail.com
##
##    This program is free software: you can redistribute it and/or modify
##    it under the terms of the GNU General Public License as published by
##    the Free Software Foundation, either version 3 of the License, or
##    (at your option) any later version.
##
##    This program is distributed in the hope that it will be useful,
##    but WITHOUT ANY WARRANTY; without even the implied warranty of
##    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##    GNU General Public License for more details.
##
##    You should have received a copy of the GNU General Public License
##

# pylint: disable=C0103

"""

Parse timetracker line-by-line format:

Time-tracker line-by-line format consists of a simple text file with line in the format:
    %DATE %TIME %trackercmd
e.g.
    2015-06-01 18.52 start experiment calculation
    ....
    2015-06-01 18.58 stop experiment calculation

This is initially parsed into a standardized list of dicts:
    [
     {datetime: (parsed date and time), action: (start/stop): label: (rest of the line)},
     ...
    ]

This can then be grouped by label:
    lines_by_label = {<label>: [list of all entries for that label]}

Note: A line is just that: a line.
      In order for a time tracking entry to be complete, it must have two lines: start and stop.

This is then further processed to create matching start-stop timespans:
    timespans_by_label = {<label>:
        [
          {starttime: <start datetime>, timespan: <stop-time minus start-time), label: (label), comment: None}
        ]}


Timeline Visualization:
* matplotlib + hlines: http://stackoverflow.com/questions/7684475/plotting-labeled-intervals-in-matplotlib-gnuplot
* Not: matplotlib plot_date: http://matplotlib.org/api/pyplot_api.html?highlight=plot_date#matplotlib.pyplot.plot_date
*

Other timeline tools:
* http://grass.osgeo.org/grass71/manuals/wxGUI.timeline.html
* http://www.simile-widgets.org/timeline/

"""

import sys
import os
import re
import yaml
import glob
import argparse
from collections import defaultdict
import logging
logger = logging.getLogger(__name__)
from datetime import datetime, timedelta


line_regex_str = r"(?P<datetime>[\d\.-]+[:\s][\d\.:]+)\s+(?P<action>\w+)\s+(?P<label>.+)"
line_pat = re.compile(line_regex_str)
datestrptime = "%Y-%m-%d %H.%M" #"yyyy-mm-dd HH.MM"


def parse_files(filenames):
    """
    All filenames are parsed into the same data structure.
    """
    lines = []
    lines_by_label = defaultdict(list)
    for filename in filenames:
        with open(filename) as filep:
            for lineno, line in enumerate(filep):
                match = line_pat.match(line.strip())
                if not match:
                    logger.info("%s:%s did not match line regex.", filename, lineno)
                    #logger.info("{}:{} did not match line regex.", filename, lineno)
                    continue
                label = match.group("label")
                action = match.group("action")
                time = datetime.strptime(match.group("datetime"), datestrptime)
                linedict = {"datetime": time,
                            "action": action,
                            "label": label,
                            "lineno": lineno
                           }
                lines.append(linedict)
                lines_by_label[label].append(linedict)
    return lines_by_label

def find_timespans_by_label(lines_by_labels):
    """
    Input dict with lines by labels,
    calculate "entries" by for each start-line, find the next stop line.
    """
    timespans_by_label = defaultdict(list)
    for label, lines in lines_by_labels.items():
        for line in lines:
            #print(line)
            action = line["action"]
            if action == "start":
                entry = {"label": label, "start": line["datetime"], "lineno": line["lineno"]}
                try:
                    next_stop = next(line for line in lines
                                     if line["lineno"] > entry["lineno"] and line["action"] == "stop"
                                     and line["datetime"] >= entry["start"])
                except StopIteration:
                    logger.warning("Stoptime for entry %s @ %s WAS NOT FOUND",
                                   entry["label"], entry["start"])
                    continue
                next_start = next((line for line in lines
                                   if line["lineno"] > entry["lineno"] and line["action"] == "start"
                                   and line["datetime"] > entry["start"]), None)
                if next_start and next_stop["datetime"] > next_start["datetime"]:
                    logger.warning("Stoptime for entry %s @ %s is later than the next "\
                                   "start time for this label: %s > %s",
                                   entry["label"], entry["start"], next_stop["datetime"], next_start["datetime"])
                    #logger.warning("Stoptime for entry {entry[label]} @ {entry[start]} is later than the next "\
                    #               "start time for this label: {next_stop[datetime]} > {next_start[datetime]}",
                    #               entry=entry, next_stop=next_stop, next_start=next_start)
                entry["stop"] = next_stop["datetime"]
                entry["timespan"] = entry["stop"] - entry["start"]  # datetime - datetime -> timedelta
                timespans_by_label[label].append(entry)
    return timespans_by_label


def plot_timeline(timespans_by_label):
    """
    Make a time line with timespans by label.

    Make sure you have a suitable matplotlib backend available and optionally configured
    (is done in the rcparams).
    """
    import matplotlib
    matplotlib.use("Qt5Agg")
    from matplotlib import pyplot
    from matplotlib.dates import DateFormatter, WeekdayLocator, DayLocator, HourLocator, MinuteLocator
    from matplotlib.dates import MO #, TU, WE, TH, FR, SA, SU

    #def timelines(y, xstart, xstop, color='b'):
    #    """Plot timelines at y from xstart to xstop with given color."""
    #    pyplot.hlines(y, xstart, xstop, color, lw=4)
    #    pyplot.vlines(xstart, y+0.03, y-0.03, color, lw=2)
    #    pyplot.vlines(xstop, y+0.03, y-0.03, color, lw=2)

    labels = list(timespans_by_label.keys())
    colors = list("rgbcmyk")
    for i, label in enumerate(labels, 1):
        entries = timespans_by_label[label]
        for entry in entries:
            pyplot.hlines(i, entry["start"], entry["stop"], colors[i], lw=12)
    #Setup the plot
    ax = pyplot.gca()
    pyplot.yticks(range(1, len(labels)+1), labels)

    min_startdate = min(entry["start"]
                        for entries in timespans_by_label.values() for entry in entries)
    max_stopdate = max(entry["stop"]
                       for entries in timespans_by_label.values() for entry in entries)

    timespan = max_stopdate - min_startdate
    ax.xaxis_date()
    if timespan > timedelta(7):
        # If timespan is larger than 7 days:
        ax.xaxis.set_major_formatter(DateFormatter("%y/%m/%d %H"))
        ax.xaxis.set_major_locator(WeekdayLocator(byweekday=MO))  # tick every monday
        ax.xaxis.set_minor_locator(HourLocator(byhour=0))  # tick every midnight
    elif timespan > timedelta(1):
        ax.xaxis.set_major_formatter(DateFormatter("%m/%d %H:%M"))
        #ax.xaxis.set_major_locator(WeekdayLocator(byweekday=range(7)))  # tick every day
        ax.xaxis.set_major_locator(DayLocator())  # tick every day, v2
        ax.xaxis.set_minor_locator(HourLocator())  # tick every hour
    #elif timespan > timedelta(1):
    else:
        ax.xaxis.set_major_formatter(DateFormatter("%H:%M"))
        #ax.xaxis.set_major_locator(WeekdayLocator(byweekday=range(7)))  # tick every day
        ax.xaxis.set_major_locator(HourLocator())  # tick every day, v2
        ax.xaxis.set_minor_locator(MinuteLocator())  # tick every minute



    # Graph limits:
    pyplot.xlim(min_startdate-0.1*timespan, max_stopdate+0.1*timespan)    # You have to set this.
    pyplot.ylim(0, len(labels)+1)

    pyplot.xlabel('Time')
    #pyplot.interactive(True)
    pyplot.ioff()
    #pyplot.ion()
    print("\n\nShowing plot...")
    pyplot.tight_layout()
    pyplot.show()



def parse_args(argv=None):
    """
    Parse command line arguments.
    """

    parser = argparse.ArgumentParser(description="Cadnano apply sequence script.")
    parser.add_argument("--verbose", "-v", action="count", help="Increase verbosity.")
    #parser.add_argument("--profile", "-p", action="store_true", help="Profile app execution.")
    #parser.add_argument("--print-profile", "-P", action="store_true", help="Print profiling statistics.")
    #parser.add_argument("--profile-outputfn", default="scaffold_rotation.profile",
                        #help="Save profiling statistics to this file.")

    #parser.add_argument("--seqfile", "-s", nargs=1, required=True, help="File containing the sequences")
    #parser.add_argument("seqfile", help="File containing the sequences")

    #parser.add_argument("--seqfileformat", help="File format for the sequence file.")

    # NOTE: Windows does not support wildcard expansion in the default command line prompt!

    parser.add_argument("--timelineplot", "-p", action="store_true", help="Produce a time-line plot.")
    parser.add_argument("--no-timelineplot", action="store_false", dest="timelineplot",
                        help="Do not produce a time-line plot.")

    ## TODO: Filter dates --startdate-after  --enddate-before
    ## TODO: Filter labels
    ## TODO: More plot types

    parser.add_argument("files", nargs="+", metavar="file",
                        help="One or more files with time tracker data in simple line-by-line format.")

    return parser, parser.parse_args(argv)


def process_args(argns=None, argv=None):
    """
    Process command line args and return a dict with args.

    If argns is given, this is used for processing.
    If argns is not given (or None), parse_args() is called
    in order to obtain a Namespace for the command line arguments.

    Will expand the entry "cadnano_files" using glob matching, and print a
    warning if a pattern does not match any files at all.

    If argns (given or obtained) contains a "config" attribute,
    this is interpreted as being the filename of a config file (in yaml format),
    which is loaded and merged with the args.

    Returns a dict.
    """
    if argns is None:
        _, argns = parse_args(argv)
    args = argns.__dict__.copy()

    # Load config with parameters:
    if args.get("config"):
        with open(args["config"]) as fp:
            cfg = yaml.load(fp)
        args.update(cfg)

    # On windows, we have to expand glob patterns manually:
    file_pattern_matches = [(pattern, glob.glob(pattern)) for pattern in args['files']]
    for pattern in (pattern for pattern, res in file_pattern_matches if len(res) == 0):
        print("WARNING: File/pattern '%s' does not match any files." % pattern)
    args['files'] = [fname for pattern, res in file_pattern_matches for fname in res]

    return args




def main(argv=None):
    """ Main driver """
    logging.basicConfig(level=10)
    args = process_args(None, argv)
    lines_by_label = parse_files(args['files'])
    timespans_by_label = find_timespans_by_label(lines_by_label)
    if args["timelineplot"]:
        plot_timeline(timespans_by_label)



def test():
    """ Primitive test. """
    testfile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tests", "testdata", "TimeTracker.txt")
    args = {"files": [testfile]}
    logging.basicConfig(level=10) #, style="{")
    lines_by_label = parse_files(args['files'])
    #print("\nlines_by_label:")
    #print(lines_by_label)
    timespans_by_label = find_timespans_by_label(lines_by_label)
    #print("\ntimespans_by_label:")
    #print(timespans_by_label)
    plot_timeline(timespans_by_label)



if __name__ == '__main__':
    if "--test" in sys.argv:
        test()
    else:
        main()

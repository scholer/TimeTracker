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
# New version: # can be used for making tags, comma can be used to make a comment. E.g.
#   2015-06-08 12.22 start Litterature review #work #fun, M.B. Francis paper/reagents/synthesis
line_regex_str = r"^(?P<datetime>[\d\.-]+[:\s][\d\.:]+)\s+(?P<action>\w+)\s+(?P<label>[^#,]+)"\
                 r"(?P<tags>(\s*#\w+)*)(,\s+(?P<comment>.+))?$"
line_pat = re.compile(line_regex_str)
datestrptime = "%Y-%m-%d %H.%M" #"yyyy-mm-dd HH.MM"


def parse_files(filenames):
    """
    All filenames are parsed into the same data structure, a list of dicts with items:
        {datetime, action, label, lineno}
    """
    lines = []
    for filename in filenames:
        with open(filename) as filep:
            for lineno, line in enumerate(filep):
                match = line_pat.match(line.strip())
                if not match:
                    logger.info("%s:%s did not match line regex.", filename, lineno)
                    continue
                linedict = match.groupdict()
                linedict["label"] = linedict["label"].title()
                linedict["action"] = linedict["action"].lower()
                linedict["datetime"] = datetime.strptime(linedict["datetime"], datestrptime)
                linedict["filename"] = filename
                linedict["lineno"] = lineno
                lines.append(linedict)
    return lines


def get_lines_by_label(lines, auto_stop_on_start=True, discart_redundant_stops=False):
    """
    lines is a list of dicts as returned by parse_files.
    If auto_stop_on_start is True (default), then
    """
    # First sort lines by datetime, in place:
    # (this makes downstream processing much easier)
    def sort_key(line):
        """
        Sorting is not actually trivial. We might have:
            16.00 start activity1
            16.00 stop activity1    # Stopped within less than 1 minute
        or
            15.50 start activity2
            16.00 stop activity2
            16.00 start activity1   # A new activity started right after
            16.00 stop activity1    # and is then stopped again
        In this case, sorting by lineno might be the best option...
        This might provide issues in the above case if sourced from multiple files,
        i.e. if you stop one activity in one file and start another in the same minute in another file.
        """
        return (line["datetime"], line["filename"], line["lineno"], line["label"], line["action"])
    lines.sort(key=sort_key)
    lines_by_label = defaultdict(list)
    for linedict in lines:
        label = linedict["label"]
        # Do not add stop entries if this activity has already been stopped:
        if discart_redundant_stops and linedict["label"] == "stop" \
        and (not lines_by_label[label] or lines_by_label[label][-1] == "stop"):
            # dont add stop entry if non-empty list or the last entry wasn't stop:
            # Note: empty lists normally shouldn't happen...
            logger.debug("Not adding redundant stop entry: %s", linedict)
            continue
        # Stop running activities if auto_stop_on_start and action=start:
        if auto_stop_on_start and linedict["action"] == "start":
            for other_label, labelentries in lines_by_label.items():
                # If the last entry is start, then add an entry that closes it:
                if labelentries[-1]["action"] == "start":
                    stopdict = {"action": "stop", "label": other_label, "datetime": linedict["datetime"]}
                    logger.debug("Adding automatic stop entry: %s", stopdict)
                    labelentries.append(stopdict)
        linedict.pop("lineno")
        linedict.pop("filename")
        # Add entry:
        lines_by_label[linedict["label"]].append(linedict)

    return lines_by_label


def find_timespans_by_label(lines_by_label):
    """
    Input dict with lines by labels,
    calculate "entries" by for each start-line, find the next stop line.
    """
    timespans_by_label = defaultdict(list)
    for label, lines in lines_by_label.items():
        for i, line in enumerate(lines):
            #print(line)
            action = line["action"]
            if action == "start":
                # Now that the lines are sorted, we can simplify our checks:
                entry = {"label": label, "start": line["datetime"]}
                try:
                    next_stop = next(line for line in lines[i+1:] if line["action"] == "stop")
                    entry["stop"] = next_stop["datetime"]
                except StopIteration:
                    logger.warning("Stoptime for entry %s @ %s WAS NOT FOUND. Setting stoptime to now.",
                                   entry["label"], entry["start"])
                    entry["stop"] = datetime.now()
                # Check for overlapping timespans. This shouldn't happen if using auto_stop_on_start=True
                next_start = next((line for line in lines[i+1:] if line["action"] == "start"), None)
                if next_start and next_stop["datetime"] > next_start["datetime"]:
                    logger.warning("Stoptime for entry %s @ %s is later than the next "\
                                   "start time for this label: %s > %s",
                                   entry["label"], entry["start"], next_stop["datetime"], next_start["datetime"])
                entry["timespan"] = entry["stop"] - entry["start"]  # datetime - datetime -> timedelta
                timespans_by_label[label].append(entry)
    return timespans_by_label

def filter_timespans(timespans_by_label, args):
    """ Filter timespans by criteria in args, e.g. start/end time. """
    time_criteria = ("start_before", "start_after", "end_before", "end_after")
    if not any(args.get(criteria) for criteria in time_criteria):
        logger.debug("No time criteria specified... %s", args)
        return timespans_by_label
    timespans_before_filtering = len([timespan for timespans in timespans_by_label.values() for timespan in timespans])
    for criteria in time_criteria:
        if not args.get(criteria):
            continue
        logger.debug("Filtering timespans_by_label on %s %s", criteria, args[criteria])
        crit_key, side = criteria.split("_")
        if side == "after":
            time_ok = lambda timespan: timespan[crit_key] >= args[criteria]     # pylint: disable=W0640
        elif side == "before":
            time_ok = lambda timespan: timespan[crit_key] <= args[criteria]     # pylint: disable=W0640
        else:
            print("COULD NOT PARSE criteria %s -- %s, %s" % (criteria, crit_key, side))
        timespans_by_label = {label: [timespan for timespan in timespans if time_ok(timespan)]
                              for label, timespans in timespans_by_label.items()}
    timespans_after_filtering = len([timespan for timespans in timespans_by_label.values() for timespan in timespans])
    logger.debug("Timespans before/after filtering: %s / %s", timespans_before_filtering, timespans_after_filtering)
    return timespans_by_label

def filter_labels(timespans_by_label, args):
    """ Filter timespans by labels in args. """
    if args.get("labels"):
        args["labels"] = [label.title() for label in args["labels"]] # ensure title case comparison
        logger.debug("Including only labels: %s", args["labels"])
        # Need to make list, otherwise we get RuntimeError for changing dict size while iterating over it
        for key in list(timespans_by_label.keys()):
            if key not in args["labels"]:
                logger.debug("Removing timespans for label %s", key)
                timespans_by_label.pop(key)
    if args.get("exclude_labels"):
        args["exclude_labels"] = [label.title() for label in args["exclude_labels"]]
        logger.debug("Excluding labels: %s", args["exclude_labels"])
        for key in list(timespans_by_label.keys()):
            if key in args["exclude_labels"]:
                logger.debug("Removing timespans for label %s", key)
                timespans_by_label.pop(key)
    return timespans_by_label

def filter_empty(timespans_by_label):
    """ Remove zero-length items in timespans_by_labels (can happen after filtering by start/end time). """
    for key in list(timespans_by_label.keys()):
        if not timespans_by_label[key]:
            logger.debug("Removing label with zero timespans: %s", key)
            timespans_by_label.pop(key)
    return timespans_by_label

def filter_main(timespans_by_label, args):
    """ Perform all filtering, as specified by args. """
    filter_labels(timespans_by_label, args)
    timespans_by_label = filter_timespans(timespans_by_label, args)
    if args["discart_empty_labels"]:
        filter_empty(timespans_by_label)
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

    labels = sorted(timespans_by_label.keys())
    colors = list("rgbcmyk")
    colors = colors*int(len(labels)/len(colors)+1)    # Make sure we have more colors than labels
    for i, label in enumerate(labels):
        entries = timespans_by_label[label]
        for entry in entries:
            pyplot.hlines(i+1, entry["start"], entry["stop"], colors[i], lw=12)
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
    parser.add_argument("--testing", action="store_true", help="Run app in simple test mode.")
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

    ## DONE: auto_stop_on_start and discart_redundant_stops flags
    parser.add_argument("--no-auto-stop-on-start", "-A", action="store_false", dest="auto_stop_on_start")
    parser.add_argument("--auto-stop-on-start", "-a", action="store_true",
                        help="Automatically stop running activities when a new activity is started.")

    parser.add_argument("--no-discart-redundant-stops", "-D", action="store_false", dest="discart_redundant_stops")
    parser.add_argument("--discart-redundant-stops", "-d", action="store_true",
                        help="Discart redundant stop entries.")

    ## Done: Filter dates --start-after  --end-before
    ## Done: Filter labels
    ## Done: Add short-hand arguments for date filtering: --today, --yesterday, --this-week, --last-week, --this-month
    ## TODO: More plot types with totals (pie charts, bar plots, etc)
    ## TODO: User-customized colors for labels
    ## TODO: Add user-defined label order

    parser.add_argument("--start-after", nargs=2,
                        help="Only consider entries with a start date/time after this point (yyyy-mm-dd HH:MM) "\
                             "Note that you must specify both date and time, separated by space.")
    parser.add_argument("--start-before", nargs=2, help="Only consider entries with startdate before this.")
    parser.add_argument("--end-after", nargs=2, help="Only consider entries with enddate after this.")
    parser.add_argument("--end-before", nargs=2, help="Only consider entries with enddate before this.")

    parser.add_argument("--today", action="store_true", help="Only consider entries with startdate during today. "
                        "(Note that date short-hands are mutually exclusive at the moment.)")
    parser.add_argument("--yesterday", action="store_true",
                        help="Only consider entries with startdate during yesterday.")
    parser.add_argument("--this-week", action="store_true",
                        help="Only consider entries with startdate during this week.")

    parser.add_argument("--labels", "-l", nargs="+", help="Only include these labels.")
    parser.add_argument("--exclude-labels", nargs="+", help="Exclude these labels.")

    parser.add_argument("--discart-empty-labels", action="store_true",
                        help="Discart labels with zero timespans (can happen after filtering).")

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

    now = datetime.now()
    if args.get("today"):
        args["start_after"] = datetime(now.year, now.month, now.day)
    if args.get("yesterday"):
        args["end_before"] = datetime(now.year, now.month, now.day)     # end before today midnight
        args["start_after"] = args["end_before"] - timedelta(1)         # after yesterday midnight
    if args.get("this_week"):
        args["start_after"] = datetime(now.year, now.month, now.day) - timedelta(6)


    time_criteria = ("start_before", "start_after", "end_before", "end_after")
    for criteria in time_criteria:
        if (not args.get(criteria)) or isinstance(args[criteria], datetime):
            continue
        if isinstance(args[criteria], list):
            args[criteria] = " ".join(args[criteria])
        args[criteria] = datetime.strptime(args[criteria], "%Y-%m-%d %H:%M")

    return args


def main(argv=None):
    """ Main driver """
    logging.basicConfig(level=10)
    args = process_args(None, argv)
    lines = parse_files(args['files'])
    lines_by_label = get_lines_by_label(lines)
    timespans_by_label = find_timespans_by_label(lines_by_label)
    timespans_by_label = filter_main(timespans_by_label, args)
    if args["timelineplot"]:
        plot_timeline(timespans_by_label)

def test1():
    """ Primitive test. """
    testfile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tests", "testdata", "TimeTracker.txt")
    args = {"files": [testfile],
            #"start_before": datetime(2015, 6, 2),
            #"exclude_labels": ["gloves on"],
            #"labels": ["gloves on", "experiment calculation"],
            "today": True,
           }
    argv = ["--today", testfile]
    args = process_args(None, argv)
    print("args: %s")
    logging.basicConfig(level=10) #, style="{")
    lines = parse_files(args['files'])
    print("\nLines:")
    print(yaml.dump(lines))
    lines_by_label = get_lines_by_label(lines, auto_stop_on_start=True, discart_redundant_stops=True)
    print("\nLines by label:")
    print(yaml.dump(lines_by_label))
    #print("\nlines_by_label:")
    #print(lines_by_label)
    timespans_by_label = find_timespans_by_label(lines_by_label)
    #print("\ntimespans_by_label:")
    #print(timespans_by_label)

    plot_timeline(timespans_by_label)

def test2():
    """ Primitive test. """
    logging.basicConfig(level=10) #, style="{")
    testfile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tests", "testdata", "TimeTracker.txt")
    argv = ["--today", "--discart-empty-labels", testfile] + sys.argv[2:]
    print("test argv:", argv)
    main(argv)



if __name__ == '__main__':
    if "--test2" in sys.argv:
        test2()
    elif "--test" in sys.argv:
        test1()
    else:
        main()

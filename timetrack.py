#!/usr/bin/env python3
# vim:ts=4:sts=4:sw=4:tw=80:et

from datetime import datetime, date, time, timedelta

import argparse
import os
import sqlite3
import sys
import configparser

from defines import *
from randommessage import *

cfg = configparser.ConfigParser()

class ProgramAbortError(Exception):
    """
    Exception class that wraps a critical error and encapsules it for
    pretty-printing of the error message.
    """
    def __init__(self, message, cause):
        self.message = message
        self.cause = cause

    def __str__(self):
        if self.cause is not None:
            return "Error: {}\n       {}".format(self.message, self.cause)
        else:
            return "Error: {}".format(self.message)


def message(msg):
    """
    Print an informational message
    """
    print(msg)


def warning(msg):
    """
    Print a warning message
    """
    print("Warning: {}".format(msg), file=sys.stderr)


def error(msg, ex):
    """
    Print an error message and abort execution
    """
    raise ProgramAbortError(msg, ex)

def dbSetup():
    """
    Create a new SQLite database in the user's home, creating and initializing
    the database if it doesn't exist. Returns an sqlite3 connection object.
    """
    con = sqlite3.connect(os.path.expanduser(cfg['db']['file']),
                          detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row

    dbVersion = con.execute("PRAGMA user_version").fetchone()['user_version']
    if dbVersion == 0:
        # database is uninitialized, create the tables we need
        con.execute("BEGIN EXCLUSIVE")
        con.execute("""
                CREATE TABLE times (
                      type TEXT NOT NULL CHECK (
                           type == "{}"
                        OR type == "{}"
                        OR type == "{}"
                        OR type == "{}"
                        OR type == "{}"
                        OR type == "{}"
                        OR type == "{}")
                    , ts TIMESTAMP NOT NULL
                    , PRIMARY KEY (type, ts)
                )
            """.format(ACT_ARRIVE, ACT_BREAK, ACT_RESUME, ACT_LEAVE, ACT_SICK,
                ACT_VACTATION, ACT_FZA))
        con.execute("PRAGMA user_version = 1")
        con.commit()
    # database upgrade code would go here

    return con


def addEntry(con, type, ts):
    con.execute("INSERT INTO times (type, ts) VALUES (?, ?)", (type, ts))
    con.commit()


def getLastType(con):
    cur = con.execute("SELECT type FROM times ORDER BY ts DESC LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return None
    return row['type']


def getLastTime(con):
    cur = con.execute("SELECT ts FROM times ORDER BY ts DESC LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return None
    return row['ts']


def startTracking(con):
    """
    Start your day: Records your arrival time in the morning.
    """
    # Make sure you're not already at work.
    lastType = getLastType(con)
    if lastType is not None and lastType != ACT_LEAVE:
        error(randomMessage(MSG_ERR_HAVE_NOT_LEFT), None)

    arrivalTime = datetime.now()
    addEntry(con, ACT_ARRIVE, arrivalTime)
    message(randomMessage(MSG_SUCCESS_ARRIVAL, arrivalTime))


def suspendTracking(con):
    """
    Suspend tracking for today: Records the start of your break time. There can
    be an infinite number of breaks per day.
    """

    # Make sure you're currently working; can't suspend if you weren't even
    # working
    lastType = getLastType(con)
    lastTime = getLastTime(con)
    if lastType not in [ACT_ARRIVE, ACT_RESUME]:
        error(randomMessage(MSG_ERR_NOT_WORKING, lastType), None)

    breakTime = datetime.now()
    addEntry(con, ACT_BREAK, breakTime)
    message(randomMessage(MSG_SUCCESS_BREAK, breakTime, lastTime))


def resumeTracking(con):
    """
    Resume tracking after a break. Records the end time of your break. There
    can be an infinite number of breaks per day.
    """

    # Make sure you're currently taking a break; can't resume if you were not
    # taking a break
    lastType = getLastType(con)
    lastTime = getLastTime(con)
    if lastType != ACT_BREAK:
        error(randomMessage(MSG_ERR_NOT_BREAKING, lastType), None)

    resumeTime = datetime.now()
    addEntry(con, ACT_RESUME, resumeTime)
    message(randomMessage(MSG_SUCCESS_RESUME, resumeTime, lastTime))


def endTracking(con):
    """
    End tracking for the day. Records the time of your leave.
    """
    # Make sure you've actually been at work. Can't leave if you're not even
    # here!
    lastType = getLastType(con)
    if lastType not in [ACT_ARRIVE, ACT_RESUME]:
        error(randomMessage(MSG_ERR_NOT_WORKING, lastType), None)

    leaveTime = datetime.now()
    addEntry(con, ACT_LEAVE, leaveTime)
    message(randomMessage(MSG_SUCCESS_LEAVE, leaveTime))


def getEntries(con, d):
    # Get the arrival for the date
    cur = con.execute("SELECT ts FROM times WHERE type = ? AND ts >= ? AND ts "
                      "< ? ORDER BY ts ASC LIMIT 1",
                      (ACT_ARRIVE, datetime.combine(d, time()),
                       datetime.combine(d + timedelta(days=1), time())))
    res = cur.fetchone()
    if not res:
        error("There is no arrival on {:%d.%m.%Y}".format(d), None)
    startTime = res['ts']

    # Use the end of the day as endtime
    endTime = datetime.combine(d + timedelta(days=1), time())

    # Get all entries between the start time, and the end time (if applicable)
    cur = con.execute("SELECT type, ts FROM times WHERE ts >= ? AND ts <= "
                      "? ORDER BY ts ASC", (startTime, endTime))
    return cur


def getWorkTimeForDay(con, d=date.today()):
    summaryTime = timedelta(0)
    arrival = None
    for type, ts in getEntries(con, d):
        if not arrival:
            if type not in [ACT_ARRIVE, ACT_RESUME]:
                error("Expected arrival while computing presence time, got {}"
                      " at {}".format(type, ts), None)
            arrival = ts
        else:
            if type not in [ACT_BREAK, ACT_LEAVE]:
                error("Expected break/leave while computing presence time, got"
                      " {} at {}".format(type, ts), None)
            summaryTime += ts - arrival
            arrival = None
    if arrival:
        # open end
        summaryTime += datetime.now() - arrival

    return (arrival is not None, summaryTime)


def dayStatistics(con, offset=0):
    headerPrinted = False
    targetDay = date.today() + timedelta(days=offset)
    for type, ts in getEntries(con, targetDay):
        if not headerPrinted:
            message("Time tracking entries for {:%d.%m.%Y}:".format(targetDay))
            headerPrinted = True
        message("  {:<10} {:%d.%m.%Y %H:%M}".format(type, ts))

    currentlyHere, totalTime = getWorkTimeForDay(con)
    if currentlyHere:
        message("You are currently at work.")
    message("You have worked {} h {} min".format(
        int(totalTime.total_seconds() // (60 * 60)),
        int((totalTime.total_seconds() % 3600) // 60)))


def weekStatistics(con, offset=0):
    today = date.today()
    startOfWeek = (today - timedelta(days=today.weekday()) +
                   timedelta(weeks=offset))
    endOfWeek = min(today + timedelta(days=1),
                    startOfWeek + timedelta(weeks=1))
    message("Statistics for week {:>02d}:".format(
        startOfWeek.isocalendar()[1]))

    current = startOfWeek
    dailyHours = timedelta(hours=float(WEEK_HOURS) / 5.0)
    weekTotal = timedelta(seconds=0)
    extraHours = timedelta(seconds=0)
    daysSoFar = 0

    headerPrinted = False
    currentlyHere = False

    while current < endOfWeek:
        try:
            currentlyHere, timeForDay = getWorkTimeForDay(con, current)
            daysSoFar += 1
            totalHours = int(timeForDay.total_seconds() // (60 * 60))
            totalMinutes = int((timeForDay.total_seconds() % 3600) // 60)

            timedeltaForDay = timeForDay - dailyHours
            timedeltaHours = timedeltaForDay.total_seconds() / (60 * 60)

            weekTotal += timeForDay
            extraHours += timedeltaForDay

            if not headerPrinted:
                headerPrinted = True
                message("   date         hours         diff ")
                message("  ----------   -----------   ------")
            message("  {:%d.%m.%Y}   {:>2d} h {:>02d} min    {: =+1.2f}"
                    .format(current, totalHours, totalMinutes, timedeltaHours))
        except ProgramAbortError as pae:
            if current.weekday() < 5:
                # For non-weekend days, print a message
                if not headerPrinted:
                    headerPrinted = True
                    message("   date         hours         diff ")
                    message("  ----------   -----------   ------")
                message("  {:%d.%m.%Y}    -              -".format(current))

        current += timedelta(days=1)

    weekTotalHours = int(weekTotal.total_seconds() // (60 * 60))
    weekTotalMinutes = int((weekTotal.total_seconds() % 3600) // 60)
    weekExtraHours = extraHours.total_seconds() / (60 * 60)
    message("  ----------   -----------   ------")

    if daysSoFar < 5:
        # The week isn't over, compare your current state against the ideal
        # rate
        expectation = dailyHours * daysSoFar
        expectationHours = int(expectation.total_seconds() // (60 * 60))
        expectationMinutes = int((expectation.total_seconds() % 3600) // 60)
        message("   Expected:   {:>2d} h {:>02d} min"
                .format(expectationHours, expectationMinutes))
    message("    Week {:>02d}:   {:>2d} h {:>02d} min    {: =+2.2f}"
            .format(startOfWeek.isocalendar()[1], weekTotalHours,
                    weekTotalMinutes, weekExtraHours))
    if daysSoFar < 5 or (daysSoFar == 5 and currentlyHere):
        # Calculate avg. remaining work time per day
        totalExpectation = timedelta(hours=WEEK_HOURS)
        remaining = totalExpectation - weekTotal
        remainingHours = int(remaining.total_seconds() // (60 * 60))
        remainingMinutes = int((remaining.total_seconds() % 3600) // 60)
        message("  ----------   -----------   ------")
        message("  Remaining:   {:>2d} h {:>02d} min"
                .format(remainingHours, remainingMinutes))
        if daysSoFar < 4:
            # Remaining per day
            remainingPerDay = remaining / (5 - daysSoFar)
            remainingPerDayHours = int(
                remainingPerDay.total_seconds() // (60 * 60))
            remainingPerDayMinutes = int(
                (remainingPerDay.total_seconds() % 3600) // 60)
            message("      Daily:   {:>2d} h {:>02d} min"
                    .format(remainingPerDayHours, remainingPerDayMinutes))

def time_mod(time, delta, epoch=None):
    if epoch is None:
        epoch = datetime.datetime(1970, 1, 1, tzinfo=time.tzinfo)
    return (time - epoch) % delta

def time_round(time, delta, epoch=None):
    mod = time_mod(time, delta, epoch)
    if mod < delta / 2:
       return time - mod
    return time + (delta - mod)

def time_floor(time, delta, epoch=None):
    mod = time_mod(time, delta, epoch)
    return time - mod

def time_ceil(time, delta, epoch=None):
    mod = time_mod(time, delta, epoch)
    if mod:
        return time + (delta - mod)
    return time


def validateConfig(config):
    config['db']['file'] = os.path.expanduser(config['db']['file'])
    if not (os.path.exists(config['db']['file']) or os.access(os.path.dirname(config['db']['file']), os.W_OK)):
        error("invalid db file or path not writeable", None)

def main():
    try:
        cfgfile = os.path.expanduser(CONFIG_FILE)
        cfg.read(cfgfile)
    except:
        print("Please create a " + CONFIG_FILE + " with entry: \n[db]\nfile = /path/to/database.db")
        sys.exit(1)

    validateConfig(cfg)

    parser = argparse.ArgumentParser(description='Track your work time')

    commands = parser.add_subparsers(title='subcommands', dest='action',
                                    help='description', metavar='action')
    parser_morning = commands.add_parser('morning',
                                        help='Start a new day')
    parser_break = commands.add_parser('break',
                                    help='Take a break from working')
    parser_resume = commands.add_parser('resume',
                                        help='Resume working')
    parser_continue = commands.add_parser('continue',
                                        help='Resume working, alias of "resume"')
    parser_closing = commands.add_parser('closing',
                                        help='End your work day')
    parser_day = commands.add_parser('day',
                                    help='Print daily statistics')
    parser_day.add_argument('offset', nargs='?', default=0, type=int,
                            help='Offset in days to the current one to analyze. '
                                'Note only negative values make sense here.')
    parser_week = commands.add_parser('week',
                                    help='Print weekly statistics')
    parser_week.add_argument('offset', nargs='?', default=0, type=int,
                            help='Offset in weeks to the current one to analyze. '
                                'Note only negative values make sense here.')

    args = parser.parse_args()

    actions = {
        'morning':  (startTracking, []),
        'break':    (suspendTracking, []),
        'resume':   (resumeTracking, []),
        'continue': (resumeTracking, []),
        'day':      (dayStatistics, ['offset']),
        'week':     (weekStatistics, ['offset']),
        'closing':  (endTracking, [])
    }

    if args.action not in actions:
        message('Unsupported action "{}". Use --help to get usage information.'
                .format(args.action), file=sys.stderr)
        sys.exit(1)

    try:
        connection = dbSetup()

        extraArgs = {}
        handler, extraArgNames = actions[args.action]
        for extraArgName in extraArgNames:
            if extraArgName in args:
                extraArgs[extraArgName] = getattr(args, extraArgName)

        handler(connection, **extraArgs)
        sys.exit(0)
    except ProgramAbortError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt as e:
        print()
        sys.exit(255)

if __name__ == "__main__":
    main()

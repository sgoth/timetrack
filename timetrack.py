#!/usr/bin/env python3
# vim:ts=4:sts=4:sw=4:tw=80:et

from datetime import datetime, date, time, timedelta
from dateutil.relativedelta import *

import argparse
import os
import sqlite3
import sys
import configparser
from enum import Enum, auto
from functools import reduce

from workalendar.europe.germany import Berlin
import calendar

holiday_calendar = Berlin()


from defines import *
from randommessage import *

cfg = configparser.ConfigParser()

THE_START = date(2021, 7, 12)

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
                ACT_VACATION, ACT_FZA))
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
        # without arrival we expect vacation/sick
        cur = con.execute("SELECT type, ts FROM times WHERE (type = ? OR type = "
                        "?) AND ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1",
                      (ACT_SICK, ACT_VACATION, datetime.combine(d, time()),
                       datetime.combine(d + timedelta(days=1), time())))
        res = cur.fetchone()
        if not res:
            # nothing on this day
            return []
        return [(res['type'], res['ts'])]

    # normal day here
    startTime = res['ts']

    # Use the end of the day as endtime
    endTime = datetime.combine(d + timedelta(days=1), time())

    # Get all entries between the start time, and the end time (if applicable)
    cur = con.execute("SELECT type, ts FROM times WHERE ts >= ? AND ts < "
                      "? ORDER BY ts ASC", (startTime, endTime))
    return cur

def timeAsHourMinute(time):
    return  (
                int(time.total_seconds() // (60 * 60)),
                int((time.total_seconds() % 3600) // 60)
            )


class WorkDay:
    class Type(Enum):
        Normal = auto()
        Sick = auto()
        Vacation = auto()

    class Pause:
        def __init__(self):
            self.start = None
            self.end = None

        def duration(self):
            return self.end - self.start

        def valid(self):
            return self.start and self.end

    def __init__(self):
        self.start = None
        self.end = None
        self.pauses = []
        self.type = WorkDay.Type.Normal

    def day(self):
        return date(self.start.year, self.start.month, self.start.day)

    def worktime(self):
        if not self.start or not self.end:
            return timedelta(seconds=0)

        pausetime = timedelta(seconds=0)
        for p in self.pauses:
            pausetime += p.duration()

        return self.end - self.start - pausetime

    def __str__(self):
        h, m = timeAsHourMinute(self.worktime())
        pauseString = ""
        for i in range(len(self.pauses)):
            p = self.pauses[i]
            pauseString += "{}-{}".format(p.start.strftime('%H:%M'),
                    p.end.strftime('%H:%M'))
            if i != len(self.pauses) - 1:
                pauseString += ","

        return "{}   {:2d}:{:02d}   {}".format(self.day().strftime('%a %Y-%m-%d'),
            h, m, pauseString)

class WorkMonth:
    def __init__(self, date):
        self.date = date
        self.expectedTime = None
        self.actualTime = None
        self.expectedWorkdays = None
        self.workdays = []

    def __str__(self):
        dH, dM = timeAsHourMinute(self.delta())
        return "{} ({} days):\t{}{:3d} h {:2d} min".format(
                self.date.strftime("%Y-%m"),
                len(self.workdays),
                "+" if self.delta().total_seconds() > 0 else "-",
                abs(dH), dM)

    def delta(self):
        return self.actualTime - self.expectedTime

    def deltaString(self):
        dH, dM = timeAsHourMinute(self.delta())
        return "{:2d} h {:2d} min".format(dH, dM)

    def addDay(self, day):
        self.workdays.append(day)

def getWorkTimeForDay(con, d=date.today()):
    summaryTime = timedelta(0)
    arrival = None
    day = WorkDay()
    pause = None
    for type, ts in getEntries(con, d):
        if type in [ACT_SICK, ACT_VACATION]:
            if type == ACT_SICK:
                day.type = WorkDay.Type.Sick
            elif type == ACT_VACATION:
                day.type = WorkDay.Type.Vacation

            # random start point
            day.start = datetime.combine(ts.date(), time(hour=8, minute=0, second=0))
            day.end = day.start + timedelta(hours=DAY_HOURS)

            return day
        elif type == ACT_ARRIVE:
            day.start = ts
        elif type == ACT_LEAVE:
            day.end = ts
        elif type == ACT_BREAK:
            if pause:
                error("Break while pause active at {}".format(ts), None)

            pause = WorkDay.Pause()
            pause.start = ts
        elif type == ACT_RESUME:
            if not pause:
                error("Resume while no pause active at {}".format(ts), None)

            pause.end = ts
            day.pauses.append(pause)
            pause = None
        else:
            error("Unhandled type for {}".format(type, ts), None)


    if day.start and not day.end:
        day.end = datetime.now()

    return day


def getWorkTimeForDay_old(con, d=date.today()):
    summaryTime = timedelta(0)
    arrival = None
    for type, ts in getEntries(con, d):
        if not arrival:
            if type in [ACT_SICK, ACT_VACATION]:
                return (False, summaryTime + timedelta(hours=DAY_HOURS))

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

    currentlyHere, totalTime = getWorkTimeForDay_old(con)
    if currentlyHere:
        message("You are currently at work.")
    message("You have worked {} h {} min".format(
        int(totalTime.total_seconds() // (60 * 60)),
        int((totalTime.total_seconds() % 3600) // 60)))

def monthStats(con, month=0):
    today = date.today()
    # FIXME this needs to support other years too - make month input a date
    m = WorkMonth(date(today.year, today.month if month == 0 else month, 1))

    if (date(m.date.year, m.date.month, 1) < date(THE_START.year,
        THE_START.month, 1)):
        error("Month {} before {}".format(m.date, THE_START), None)

    firstDay = holiday_calendar.find_following_working_day(date(m.date.year, m.date.month, 1))
    lastDay = date(m.date.year, m.date.month, calendar.monthrange(m.date.year, m.date.month)[1])

    if (firstDay < THE_START):
        firstDay = THE_START
    if lastDay > today:
        lastDay = lastDay.replace(day=today.day)

    while not holiday_calendar.is_working_day(firstDay):
        firstDay += timedelta(days=1)

    while not holiday_calendar.is_working_day(lastDay):
        lastDay -= timedelta(days=1)

    workingDays = holiday_calendar.get_working_days_delta(firstDay, lastDay,
            include_start=True)
    dailyHours = timedelta(hours=DAY_HOURS)

    m.expectedTime = dailyHours * workingDays
    m.expectedWorkdays = workingDays

    workedHours = timedelta(seconds=0)

    curDay = firstDay
    while curDay <= lastDay:
        if holiday_calendar.is_working_day(curDay):
            workday = getWorkTimeForDay(con, curDay)
            workedHours += workday.worktime()
            m.addDay(workday)

        curDay += timedelta(days=1)

    m.actualTime = workedHours

    return m

def printMonthStats(con, month=0):
    m = monthStats(con, month)

    print("     Day         Hours   Pauses / Comment")
    for workday in m.workdays:
        comment = ""
        if workday.type == WorkDay.Type.Sick:
            comment = "(Krank)"
        elif workday.type == WorkDay.Type.Vacation:
            comment = "(Urlaub)"
        print("{} {}".format(workday, comment))


    expectedHours, expectedMinutes = timeAsHourMinute(m.expectedTime)
    actualHours, actualMinutes = timeAsHourMinute(m.actualTime)
    print("Working hours expected for {}: {} h {} min".format(m.date.strftime("%B %y"),
        expectedHours, expectedMinutes))
    print("Actual hours {} h {} min".format(actualHours, actualMinutes))
    print("Delta hours {}".format(m.deltaString()))

    #print("Delta mins {}".format(int(m.delta().total_seconds() / 60)))

def yearlyStats(con, year=0, today=False):
    y = date.today()
    if year != 0:
        y = y.replace(year=year)

    firstMonth = THE_START.month if (y.year <= THE_START.year) else 1
    months = []

    for month in range(firstMonth, y.month + 1 if today else y.month):
        m = monthStats(con, month)
        months.append(m)
        print("{}".format(m))

    totalExpected = reduce(lambda x,y: x + y.expectedTime, months,
            timedelta(seconds=0))
    totalActual = reduce(lambda x,y: x + y.actualTime, months,
            timedelta(seconds=0))

    totalDiff = totalActual - totalExpected

    tEH, tEM = timeAsHourMinute(totalExpected)
    tAH, tAM = timeAsHourMinute(totalActual)
    print("-" * 40)
    print("total expected:\t\t{:4d} h {:02d} min".format(tEH, tEM))
    print("total actual:\t\t{:>4d} h {:02d} min".format(tAH, tAM))

    tdH, tdM = timeAsHourMinute(totalDiff)
    tdD = round(totalDiff.total_seconds() / (60 * 60 * DAY_HOURS), ndigits=2)
    print("total diff:\t\t{}{:>3d} h {:02d} min (workdays: {})".format(
        ("+" if totalDiff.total_seconds() > 0 else ""),  tdH, tdM, tdD))


def weekStatistics(con, offset=0):
    today = date.today()
    startOfWeek = (today - timedelta(days=today.weekday()) +
                   timedelta(weeks=offset))
    endOfWeek = min(today + timedelta(days=1),
                    startOfWeek + timedelta(weeks=1))
    message("Statistics for week {:>02d}:".format(
        startOfWeek.isocalendar()[1]))

    current = startOfWeek
    dailyHours = timedelta(hours=DAY_HOURS)
    weekTotal = timedelta(seconds=0)
    extraHours = timedelta(seconds=0)
    daysSoFar = 0

    headerPrinted = False
    currentlyHere = False

    while current < endOfWeek:
        try:
            currentlyHere, timeForDay = getWorkTimeForDay_old(con, current)
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
    commands.add_parser('start', help='Start a new day')

    parser_break = commands.add_parser('break',
                                    help='Take a break from working')
    commands.add_parser('pause', help='Alias to break')

    parser_resume = commands.add_parser('resume',
                                        help='Resume working')
    parser_continue = commands.add_parser('continue',
                                        help='Resume working, alias of "resume"')
    parser_closing = commands.add_parser('closing',
                                        help='End your work day')
    commands.add_parser('end', help='End your work day')
    commands.add_parser('stop', help='End your work day')
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
    parser_month = commands.add_parser('month',
                                    help='Print monthly statistics')
    parser_month.add_argument('month', nargs='?', default=0, type=int,
                            help='Month (1-12) or 0 for current')
    parser_year = commands.add_parser('year',
                                    help='Print yearly statistics')
    parser_year.add_argument('year', nargs='?', default=0, type=int,
                            help='Year (YYYY) or 0 for current')

    args = parser.parse_args()

    actions = {
        'morning':  (startTracking, []),
        'start':    (startTracking, []),
        'break':    (suspendTracking, []),
        'pause':    (suspendTracking, []),
        'resume':   (resumeTracking, []),
        'continue': (resumeTracking, []),
        'day':      (dayStatistics, ['offset']),
        'week':     (weekStatistics, ['offset']),
        'month':     (printMonthStats, ['month']),
        'year':     (yearlyStats, ['year']),
        'closing':  (endTracking, []),
        'stop':  (endTracking, []),
        'end':  (endTracking, [])
    }

    if not args.action:
        parser.print_help()
        sys.exit(1)

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

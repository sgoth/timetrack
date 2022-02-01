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
import decimal
from decimal import Decimal

holiday_calendar = Berlin()


from defines import *
from randommessage import *

cfg = configparser.ConfigParser()

THE_START = date(2021, 7, 12)

# monthly reporting as decimal hours we round as expected
decimal.getcontext().rounding = decimal.ROUND_HALF_UP

def valid_cli_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        msg = "not a valid date: {0!r}".format(s)
        raise argparse.ArgumentTypeError(msg)

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


def getLastType(con, date=None):
    if date:
        cur = con.execute("SELECT type FROM times WHERE date(ts) = date('{}')"
        "ORDER BY ts DESC LIMIT 1".format(date))
    else:
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

def revertLeave(con, date):
    con.execute("UPDATE times SET type = '{}' WHERE date(ts) = date('{}')"
    "AND type = '{}'".format(ACT_BREAK, date, ACT_LEAVE))

def startTracking(con):
    """
    Start your day: Records your arrival time in the morning.
    """
    isResume = False

    # Make sure you're not already at work.
    lastType = getLastType(con, date.today())
    if lastType is not None and lastType != ACT_LEAVE:
        error(randomMessage(MSG_ERR_HAVE_NOT_LEFT), None)

    if lastType == ACT_LEAVE:
        should = input("You already left for today - do you really want to"
                "return? [y/N] ")
        if should == 'y':
            # resumed work on same day after leave
            revertLeave(con, date.today())
            isResume = True
        else:
            raise ProgramAbortError('Aborted by user')

    arrivalTime = datetime.now()
    addEntry(con, ACT_RESUME if isResume else ACT_ARRIVE, arrivalTime)
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

def addSpecialEnties(con, type, start, end):
    delta = (end - start).days

    days = []
    for i in range(0, delta + 1):
        day = start + timedelta(days=i)
        if holiday_calendar.is_working_day(day):
            days.append(day)
            print("- {} on {}".format(type, day))
        else:
            print("-- skipping {}".format(day))

    should = input("Do you really want to add those {} days? [y/N] "
            .format(len(days)))
    if should == 'y':
        for d in days:
            print("adding {}".format(d))
            addEntry(con, type, d)

def addVacation(con, start, end):
    addSpecialEnties(con, ACT_VACATION, start, end)

def addFza(con, start, end):
    addSpecialEnties(con, ACT_FZA, start, end)

def addSick(con, start, end):
    addSpecialEnties(con, ACT_SICK, start, end)

def getEntries(con, d):
    # Get the arrival for the date
    cur = con.execute("SELECT ts FROM times WHERE type = ? AND ts >= ? AND ts "
                      "< ? ORDER BY ts ASC LIMIT 1",
                      (ACT_ARRIVE, datetime.combine(d, time()),
                       datetime.combine(d + timedelta(days=1), time())))
    res = cur.fetchone()
    if not res:
        # without arrival we expect vacation/sick
        cur = con.execute("SELECT type, ts FROM times WHERE type IN (?,?,?) "
                        "AND ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1",
                      (ACT_SICK, ACT_VACATION, ACT_FZA, datetime.combine(d, time()),
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
        FZA = auto()

    class Pause:
        def __init__(self):
            self.start = None
            self.end = None

        def duration(self):
            return self.end - self.start

        def valid(self):
            return self.start and self.end

    def __init__(self, day):
        self.start = datetime(day.year, day.month, day.day)
        self.end = self.start
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

        total = (self.end - self.start - pausetime)

        # compensate overtime
        if self.type == WorkDay.Type.FZA:
            total *= 0

        floored = total - (total % timedelta(minutes=1))
        return floored

    def to_string(self, as_hours=False):
        h, m = timeAsHourMinute(self.worktime())
        pauseString = ""
        for i in range(len(self.pauses)):
            p = self.pauses[i]
            pauseString += "{}-{}".format(p.start.strftime('%H:%M'),
                    p.end.strftime('%H:%M'))
            if i != len(self.pauses) - 1:
                pauseString += ","
        # hours as hours:minutes
        if not as_hours:
            return "{}   {:2d}:{:02d}   {}".format(self.day().strftime('%a %Y-%m-%d'),
                h, m, pauseString)
        else:
            return "{}   {:5}   {}".format(self.day().strftime('%a %Y-%m-%d'),
                    round(Decimal(self.worktime().total_seconds()) / 3600, 1) , pauseString)


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
        return "{} ({:2d} days): {:>6}{:3d} h {:02d} min".format(
                self.date.strftime("%Y-%m"),
                len(self.workdays),
                "+" if self.delta().total_seconds() > 0 else "-",
                abs(dH), dM)

    def delta(self):
        return self.actualTime - self.expectedTime

    def deltaString(self):
        dH, dM = timeAsHourMinute(self.delta())
        return "{} {:>2d} h {:02d} min".format("+" if self.delta().total_seconds() > 0
                else "", dH, dM)

    def addDay(self, day):
        self.workdays.append(day)

class WorkYear:
    def __init__(self, year):
        self.months = []
        self.year = year

    def year(self):
        return self.year

    def addMonth(self, month):
        self.months.append(month)

    def totalExpected(self):
        return reduce(lambda x,y: x + y.expectedTime, self.months, timedelta(seconds=0))

    def totalActual(self):
        return reduce(lambda x,y: x + y.actualTime, self.months, timedelta(seconds=0))

    def firstMonth(self):
        return self.months[0].date.month

    def lastMonth(self):
        return self.months[-1].date.month

    def delta(self):
        return self.totalActual() - self.totalExpected()

    def __str__(self):
        dH, dM = timeAsHourMinute(self.delta())
        return "{} ({:3d} days): {:>6}{:3d} h {:02d} min".format(self.year,
                reduce(lambda x,y: x + len(y.workdays), self.months, 0),
                "+" if self.delta().total_seconds() > 0 else "-",
                abs(dH), dM)

def getWorkTimeForDay(con, d=date.today()):
    summaryTime = timedelta(0)
    arrival = None
    day = WorkDay(d)
    pause = None
    for type, ts in getEntries(con, d):
        if type in [ACT_SICK, ACT_VACATION, ACT_FZA]:
            if type == ACT_SICK:
                day.type = WorkDay.Type.Sick
            elif type == ACT_VACATION:
                day.type = WorkDay.Type.Vacation
            elif type == ACT_FZA:
                day.type = WorkDay.Type.FZA

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

def monthStats(con, month, year):
    today = date(year, month, 1)
    m = WorkMonth(today)

    if (date(m.date.year, m.date.month, 1) < date(THE_START.year,
        THE_START.month, 1)):
        error("Month {} before {}".format(m.date, THE_START), None)

    firstDay = holiday_calendar.find_following_working_day(date(m.date.year, m.date.month, 1))
    lastDay = date(m.date.year, m.date.month, calendar.monthrange(m.date.year, m.date.month)[1])

    if (firstDay < THE_START):
        firstDay = THE_START
    # we actually want to see all days
    #if lastDay > today:
    #    lastDay = lastDay.replace(day=today.day)

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

def printMonthStats(con, month, year, with_total=False, with_ytd=False, as_hours=False):
    m = monthStats(con, month, year)

    lastDay = date(m.date.year, m.date.month, calendar.monthrange(m.date.year, m.date.month)[1])
    workdayit = iter(m.workdays)
    workday = next(workdayit)

    print("Work time for {}\n".format(m.date.strftime("%B %y")))
    print("     Day         Hours   Pauses / Comment")

    # loop all days to also show weekends/holidays
    for d in range(1, lastDay.day + 1):
        today = date(m.date.year, m.date.month, d)
        if today.weekday() == 0 or today.weekday() == 5:
            print("-" * 40)
        if workday is not None and today == workday.day():
            comment = ""
            if workday.type == WorkDay.Type.Sick:
                comment = "(Krank)"
            elif workday.type == WorkDay.Type.Vacation:
                comment = "(Urlaub)"
            elif workday.type == WorkDay.Type.FZA:
                comment = "(FZA)"

            print("{} {}".format(workday.to_string(as_hours=as_hours), comment))

            try:
                workday = next(workdayit)
            except StopIteration:
                workday = None
        else:
            comment = ""
            if holiday_calendar.is_holiday(today):
                comment = holiday_calendar.get_holiday_label(today)
            print("{}    {:<}".format(today.strftime('%a %Y-%m-%d'), comment))

    expectedHours, expectedMinutes = timeAsHourMinute(m.expectedTime)
    actualHours, actualMinutes = timeAsHourMinute(m.actualTime)

    print("-" * 40)
    print("Working hours expected: {:>3d} h {:02d} min".format(
        expectedHours, expectedMinutes))
    print("Actual hours:           {:>3d} h {:02d} min".format(actualHours, actualMinutes))
    print("Delta hours:           {:>13}".format(m.deltaString()))

    #print("Delta mins {}".format(int(m.delta().total_seconds() / 60)))

    if with_ytd:
        print()
        print()
        printYearlyStats(con, year, month)

    if with_total:
        print()
        print()
        printTotalStats(con, year)

def yearlyStats(con, year, toMonth=12, fromMonth=1):
    if (toMonth < fromMonth):
        toMonth = fromMonth

    y = date(year, toMonth, 1)
    firstMonth = THE_START.month if (y.year <= THE_START.year) else fromMonth

    workYear = WorkYear(year)

    for month in range(firstMonth, y.month + 1):
        m = monthStats(con, month, y.year)
        workYear.addMonth(m)

    return workYear

def printYearlyStats(con, year, toMonth=12, fromMonth=1):
    wy = yearlyStats(con, year, toMonth, fromMonth)

    print("Work time summary for {} {:02d}-{:02d}\n".format(wy.year,
        wy.firstMonth(), wy.lastMonth()))

    for m in wy.months:
        print("{}".format(m))

    totalExpected = wy.totalExpected()
    totalActual = wy.totalActual()
    totalDiff = totalActual - totalExpected

    tEH, tEM = timeAsHourMinute(totalExpected)
    tAH, tAM = timeAsHourMinute(totalActual)
    print("-" * 40)
    print("total expected:{:>13d} h {:02d} min".format(tEH, tEM))
    print("total actual:  {:>13d} h {:02d} min".format(tAH, tAM))

    tdH, tdM = timeAsHourMinute(totalDiff)
    tdD = round(totalDiff.total_seconds() / (60 * 60 * DAY_HOURS), ndigits=2)
    print("total diff:    {:>10}{:>3d} h {:02d} min (workdays: {})".format(
        ("+" if totalDiff.total_seconds() > 0 else ""),  tdH, tdM, tdD))

def printTotalStats(con, year, toMonth=12):
    years = []
    totalExpected = timedelta(seconds=0)
    totalActual = timedelta(seconds=0)

    print("Totals:\n")

    for y in range(THE_START.year, year + 1):
        month = 12 if y < date.today().year else date.today().month - 1
        ys = yearlyStats(con, y, month)
        totalExpected += ys.totalExpected()
        totalActual += ys.totalActual()
        print("{}".format(ys))


    totalDiff = totalActual - totalExpected

    tEH, tEM = timeAsHourMinute(totalExpected)
    tAH, tAM = timeAsHourMinute(totalActual)
    print("-" * 40)

    tdH, tdM = timeAsHourMinute(totalDiff)
    tdD = round(totalDiff.total_seconds() / (60 * 60 * DAY_HOURS), ndigits=2)
    print("total diff:    {:>10}{:>3d} h {:02d} min (workdays: {})".format(
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
        epoch = datetime(1970, 1, 1, tzinfo=time.tzinfo)
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
    parser_month.add_argument('month', nargs='?', default=date.today().month, type=int,
                            help='Month (1-12), defaults to current')
    parser_month.add_argument('year', nargs='?', default=date.today().year, type=int,
                            help='Year (YYYY), defaults to current')
    parser_month.add_argument('--with-total', dest='with_total', action='store_true',
                            help='With total-to-date summary')
    parser_month.add_argument('--with-ytd', dest='with_ytd', action='store_true',
                            help='With year-to-date summary')
    parser_month.add_argument('--as-fract-hours', dest='as_hours', action='store_true',
                            help='Report work time as fractional hours instead of hours:minutes')

    parser_year = commands.add_parser('year',
                                    help='Print yearly statistics')
    parser_year.add_argument('year', nargs='?', default=date.today().year, type=int,
                            help='Year (YYYY), defaults to current')
    parser_year.add_argument('toMonth', nargs='?', default=date.today().month-1, type=int,
                            help='Month range end, defaults to '.format(date.today().month-1))
    parser_year.add_argument('fromMonth', nargs='?', default=1, type=int,
                            help='Month range start, defaults to 1')

    parser_total = commands.add_parser('total',
                                    help='Print totally statistics')
    parser_total.add_argument('year', nargs='?', default=date.today().year, type=int,
                            help='Year (YYYY), defaults to current')
    parser_total.add_argument('toMonth', nargs='?', default=date.today().month-1, type=int,
                            help='Month range end, defaults to '.format(date.today().month-1))

    parser_vacation = commands.add_parser('vacation',
                                    help='Enter vacation dates')
    parser_vacation.add_argument('start', nargs='?', type=valid_cli_date,
                            help='Start of vacation')
    parser_vacation.add_argument('end', nargs='?', type=valid_cli_date,
                            help='End of vacation')

    parser_fza = commands.add_parser('fza',
                                    help='Enter fza dates')
    parser_fza.add_argument('start', nargs='?', type=valid_cli_date,
                            help='Start of fza')
    parser_fza.add_argument('end', nargs='?', type=valid_cli_date,
                            help='End of fza')

    parser_sick = commands.add_parser('sick',
                                    help='Enter sick dates')
    parser_sick.add_argument('start', nargs='?', type=valid_cli_date,
                            help='Start of sick')
    parser_sick.add_argument('end', nargs='?', type=valid_cli_date,
                            help='End of sick')

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
        'month':     (printMonthStats, ['month', 'year', 'with_total', 'with_ytd', 'as_hours']),
        'year':     (printYearlyStats, ['year', 'toMonth', 'fromMonth']),
        'total':     (printTotalStats, ['year', 'toMonth']),
        'vacation': (addVacation, ['start', 'end']),
        'fza': (addFza, ['start', 'end']),
        'sick': (addSick, ['start', 'end']),
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

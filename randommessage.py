from defines import *
from datetime import datetime
import random

def randomMessage(type, *args):
    messageList = []
    timestamp = "{}: ".format(datetime.now().strftime("%H:%M"))

    ###########
    # Arrival #
    ###########
    if type == MSG_SUCCESS_ARRIVAL:
        if len(args) > 0:
            arrivalTime = args[0]
            if arrivalTime.hour <= 7:
                messageList.append("The early bird catches the worm. Welcome"
                                   " and have a nice day!")
            elif arrivalTime.hour <= 9:
                messageList.append("Good morning.")
            elif arrivalTime.hour >= 10:
                messageList.append("Coming in late today? Have fun working"
                                   " anyway.")

            if arrivalTime.weekday() == 0:  # Monday
                messageList.append("Have a nice start into the fresh week!")
                messageList.append("New week, new luck!")
            elif arrivalTime.weekday() == 4:  # Friday
                messageList.append("Last day of the week! Almost done! Keep "
                                   " going!")
                messageList.append("Just a couple more hours until weekend."
                                   " Have fun!")
            elif arrivalTime.weekday() == 5:  # Saturday
                messageList.append("Oh, so they made you work on Saturday? I'm"
                                   " sorry :/")
                messageList.append("Saturday, meh. Hang in there, it'll be"
                                   " over soon.")

        messageList.append("Welcome and have a nice day!")

    #########
    # Break #
    #########
    elif type == MSG_SUCCESS_BREAK:
        breakTime = None
        workStartTime = None
        if len(args) > 0:
            breakTime = args[0]
        if len(args) > 1:
            workStartTime = args[1]

        if breakTime is not None and workStartTime is not None:
            duration = breakTime - workStartTime
            durationHours = int(duration.total_seconds() // 3600)
            durationMinutes = int(
                (duration.total_seconds() - (durationHours * 3600)) // 60)
            msgText = ""
            if durationHours > 1:
                msgText += "{:d} hours".format(durationHours)
            elif durationHours == 1:
                msgText += "{:d} hour".format(durationHours)

            # avoid 1 hour 2 minutes
            if durationHours > 0 and durationMinutes > 2: 
                msgText += " and "

            if durationHours == 0 or durationMinutes > 2:
                if durationMinutes > 1:
                    msgText += "{:02d} minutes".format(durationMinutes)
                else:
                    msgText += "{:02d} minutes".format(durationMinutes)

            msgText += " of work."

            # more than 4h, time for a break
            if duration.total_seconds() >= 4 * 60 * 60: 
                msgText += " Time for a well-deserved break."
            else:
                msgText += " I guess a coffee break wouldn't hurt, would it?"

            messageList.append(msgText)

        if breakTime is not None:
            if breakTime.hour >= 11 and breakTime.hour <= 13:
                messageList.append("{:%H:%M}. A good time for lunch.".format(
                    breakTime))
            if breakTime.hour < 11:
                messageList.append("{0.hour} o'clock. Breakfast time!".format(
                    breakTime))
            if breakTime.hour > 13:
                messageList.append("Coffee?")
                messageList.append("Good idea, take a break and relax a"
                                   " little.")

        messageList.append("Enjoy your break!")
        messageList.append("Relax a little and all your problems will have"
                           " gotten simpler once you're back :-)")
        messageList.append("Bye bye!")

    ################
    # End of break #
    ################
    elif type == MSG_SUCCESS_RESUME:
        resumeTime = None
        breakStartTime = None
        if len(args) > 0:
            resumeTime = args[0]
        if len(args) > 1:
            breakStartTime = args[1]

        if resumeTime is not None:
            if resumeTime.hour <= 12:
                messageList.append("With renewed vigour into the rest of the"
                                   " day! Welcome back.")
                messageList.append("The rest of the day right ahead, but with"
                                   " fresh strength.")
            elif resumeTime.hour >= 15:
                messageList.append("Just a few more hours. Hang in, closing"
                                   " time is near!")
                messageList.append("Almost there. Just a few more minutes.")

        if resumeTime is not None and breakStartTime is not None:
            duration = resumeTime - breakStartTime
            durationMinutes = int(duration.total_seconds() // 60)

            msgText = "{:d}".format(durationMinutes)
            if durationMinutes != 1:
                msgText += " minutes"
            else:
                msgText += " minute"
            msgText += " break. Welcome back and have fun with the rest of"
            msgText += " your day."
            messageList.append(msgText)

            if durationMinutes < 30:
                messageList.append("Quick coffee break finished? Back to work,"
                                   " getting things done!")
                messageList.append("That break certainly was a quick one!"
                                   " Welcome back!")
            elif durationMinutes >= 30 and durationMinutes < 45:
                messageList.append("Average size break, now back to work.")
            else:
                messageList.append("That was a pretty long break. You can pull"
                                   " off more then 9 hours today.")
                messageList.append("Pretty extensive {:d} minute break. Hope"
                                   " you're feeling refreshed now :)".format(
                                       durationMinutes))

        messageList.append("Welcome back at your desk. Your laptop has been"
                           " missing you.")
        messageList.append("Back into work! Enjoy!")
        messageList.append("Welcome back.")

    ###################
    # End of work day #
    ###################
    elif type == MSG_SUCCESS_LEAVE:
        endTime = None
        if len(args) > 0:
            endTime = args[0]

        if endTime is not None:
            if endTime.hour <= 14:
                messageList.append("Going home early today? Go ahead, I'm sure"
                                   " you earned it.")
                messageList.append("Short work day, enjoy your afternoon.")
            elif endTime.hour > 14 and endTime.hour < 18:
                messageList.append("Have a nice evening.")
                messageList.append("Bon appetit and enjoy your evening!")
            else:
                messageList.append("Leaving late today?")
                messageList.append("Did you just stay because the job was"
                                   " interesting or did something have to get"
                                   " done today?")
                messageList.append("Finally. Have a good night's sleep!")
            if endTime.weekday() == 4:  # Friday
                messageList.append("Friday! Have a nice weekend!")
                messageList.append("Finally, this week has come to an end.")
                messageList.append("Fuck this shit, it's Friday and I'm going"
                                   " home!")
            elif endTime.weekday() == 5:  # Saturday
                messageList.append("Ugh, somebody made you come in on"
                                   " Saturday. Enjoy your Sunday then.")
                messageList.append("About time the week was over, isn't it?")

        messageList.append("A good time to leave. Because it's always a good"
                           " time to do that. :)")
        messageList.append("You're right, go home. Tomorrow's yet another"
                           " day.")

    ######################################################################
    # Not currently working even though the requested action requires it #
    ######################################################################
    elif type == MSG_ERR_NOT_WORKING:
        msg = ("You can't leave or take a break if you're not here in the"
               " first place.")
        if len(args) > 0:
            if args[0] == ACT_BREAK:
                msg += " You are currently taking a break."
            elif args[0] == ACT_LEAVE:
                msg += " According to my data, you're still at home."
        messageList.append(msg)

    ####################################################################
    # Not currently taking a break even though you requested to resume #
    ####################################################################
    elif type == MSG_ERR_NOT_BREAKING:
        msg = ("You can't continue working if you're not currently taking"
               " a break.")
        if len(args) > 0:
            if args[0] in [ACT_ARRIVE, ACT_RESUME]:
                msg += " My data says you're here and working."
            elif args[0] == ACT_LEAVE:
                msg += " According to my data, you're still at home."
        messageList.append(msg)

    ################################################
    # Not at home, but requested to start your day #
    ################################################
    elif type == MSG_ERR_HAVE_NOT_LEFT:
        msg = "You cannot start your day when you're already (or still?) here."
        if len(args) > 0:
            if args[0] in [ACT_ARRIVE, ACT_RESUME]:
                msg += " My data says you're here and working."
            elif args[0] == ACT_BREAK:
                msg += " It seems you're taking a break."
        messageList.append(msg)

    return timestamp + random.choice(messageList)


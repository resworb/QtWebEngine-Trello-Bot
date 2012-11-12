#!/usr/bin/env python
# -*- coding: utf-8 -*-

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from datetime import datetime, time

import cPickle as pickle
import os
import smtplib
import logging
import time as tmtime

NICK = "StatusBot"
SERVER = "chat.freenode.net"
PORT = 8001
CHANNEL = "#qtwebkit"

# SERVER = "10.60.1.22"
# PORT = 6667
# CHANNEL = "#webkit"

PEOPLE = [
    "cmarcelo",
    "darktears",
    "jeez_",

    "bbandix",
    "elproxy",
    "jturcotte",
    "torarne",
    "tronical",
    "zalbisser",

    "carewolf",
    "mibrunin",
    "zalan",

    "Ossy",
    "Zoltan",
    "abalazs",
    "azbest_hu",
    "dicska",
    "kadam",
    "kbalazs",
    "kkristof",
    "hnandor",
    "loki04",
    "reni",
    "rtakacs",
    "stampho",
    "szledan",
    "tczene",
    "zherczeg",
    ]

SMTP = "smtp.gmail.com"
FROM = "Qt WebKit StatusBot <qtwebkit-statusbot@openbossa.org>"
TO = "webkit-qt@lists.webkit.org"
# TO = "caio.oliveira@openbossa.org"

MEETING_HOUR = (15, 00)
MEETING_REMIND_HOUR = (18, 00)
MEETING_END_TIME = (18, 30)

def offset(hour, minute = 0):
    nowtime = tmtime.gmtime()
    nexttime = [item for item in nowtime]
    if nowtime.tm_hour >= hour and nowtime.tm_min >= minute:
        nexttime[2] += 1
    nexttime[3] = hour
    nexttime[4] = minute

    return int(tmtime.mktime(nexttime) -  tmtime.mktime(nowtime))

class StatusBotClient(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname

    nickname = property(_get_nickname)

    def _missing_participants_sorted(self):
        return ', '.join(sorted(self.factory.missing_participants))

    def _remind_missing_participants(self):
        if self.factory.ongoing and self.factory.missing_participants:
            logging.warning("Reminding missing participants")
            self.notice(self.factory.channel, "Status reminder!")
            self.describe(self.factory.channel, "*prods* %s" % self._missing_participants_sorted())

    def _send_mail(self, subject, contents):
        logging.warning("Sending email.")
        body = "To: %s\r\nFrom: %s\r\nSubject: %s\r\n\r\n" % (TO, FROM, subject)
        body += contents
        mail_server = smtplib.SMTP(SMTP, 587)
        mail_server.set_debuglevel(1)
        mail_server.ehlo()
        mail_server.starttls()
        mail_server.ehlo()
        mail_server.login("qtwebkit-statusbot@openbossa.org", "indt2011")
        mail_server.sendmail(FROM, TO, body)
        mail_server.quit()
        logging.warning("Email sent.")

    def _send_minutes_mail(self):
        subject = "Minutes from the Status Meeting in %s on Freenode IRC network" % self.factory.channel

        contents = "Updates:\n"
        for (k, v) in self.factory.status_messages.items():
            contents += "  * %s %s\n" % (k, v)
        if self.factory.missing_participants:
            contents += "\nMissing updates from: %s\n" % self._missing_participants_sorted()

        self._send_mail(subject, contents)

    def _end_meeting(self):
        if not self.factory.ongoing:
            return

        logging.warning("Ending meeting.")
        self.notice(self.factory.channel, "Status meeting over! Thanks all. Sending minutes to the mailing list :-)")

        if self.factory.status_messages:
            self._send_minutes_mail()

        self.factory.ongoing = False
        self.factory.missing_participants = set(self.factory.people)
        self.factory.status_messages.clear()
        self.factory.save()

    def _register_status_message(self, nickname, message):
        logging.warning("Adding status message from '%s': %s" % (nickname, message))
        self.factory.status_messages[nickname] = message
        self.factory.missing_participants.discard(nickname)
        if nickname.endswith('_'):
            self.factory.missing_participants.discard(nickname[:-1])

        if not self.factory.ongoing:
            self.notice(self.factory.channel, "%s: Status saved. Thanks!"  % (nickname))

        self.factory.save();

    def alterCollidedNick(self, nickname):
        logging.warning("Nick Collision")
        self.factory.nickname = nickname + '_'
        return self.factory.nickname

    def signedOn(self):
        logging.warning("Joining Channel: %s" % self.factory.channel)
        self.join(self.factory.channel)

        timeleft = offset(*MEETING_HOUR)
        reactor.callLater(timeleft, self._status_command)
        logging.warning("Time left till @status start: %d" % (timeleft))
        reactor.callLater(offset(*MEETING_REMIND_HOUR), self._remind_missing_participants)
        reactor.callLater(offset(*MEETING_END_TIME), self._end_meeting)

    def _status_command(self):
        channel = self.factory.channel
        if self.factory.ongoing:
            self.notice(channel, "Ongoing meeting!")
            self.notice(channel, "Missing updates from: %s" % self._missing_participants_sorted())
            return

        logging.warning("Status time!")
        self.notice(channel, "Status Time for QtWebKit hackers!")
        self.notice(channel, "Please type: /me status: <message>")

        self.factory.ongoing = True
        self.describe(channel, "*pokes* %s" % self._missing_participants_sorted())

    def privmsg(self, user, channel, message):
        if "@status" == message:
            self._status_command()

    def action(self, hostmask, channel, message):
        # An IRC hostmask is on the form "nick!user@hostname".
        nickname = hostmask.split('!')[0]
        match = "status"

        if message[:len(match)].lower() == match:
            self._register_status_message(nickname, message)

class StatusBotClientFactory(protocol.ClientFactory):
    protocol = StatusBotClient
    filename = "status.data"

    def __init__(self, nickname, channel, people):
        self.nickname = nickname
        self.channel = channel
        self.people = people
        # FIXME: These properties are here in case the connection drop, but I don't think we
        # actually recover from that. Code would be simpler if they were not here.
        self.missing_participants = set()
        self.status_messages = {}
        self.ongoing = False
        self.load()

    def clientConnectionLost(self, connector, reason):
        logging.warning("Connection Lost: %s" % reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        logging.warning("Connection Lost: %s" % reason)
        reactor.callLater(600, connector.connect)

    def save(self):
        f = open(self.filename, 'wb')
        pickle.dump(self.status_messages, f)
        f.close()

    def load(self):
        if os.path.exists(self.filename):
            f =  open(self.filename, 'rb')
            try:
                self.status_messages = pickle.load(f)
            except:
                pass
            f.close()

        timenow = datetime.utcnow().time()
        if time(*MEETING_HOUR) <= timenow and timenow < time(*MEETING_END_TIME):
            self.ongoing = True
        self.missing_participants = set(PEOPLE) - set(self.status_messages.keys())


if "__main__" == __name__:
    bot = StatusBotClientFactory(NICK, CHANNEL, PEOPLE)
    logging.warning("Trying to connect to " + SERVER)
    reactor.connectTCP(SERVER, PORT, bot)
    reactor.run()

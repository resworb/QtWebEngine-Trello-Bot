#!/usr/bin/env python
# -*- coding: utf-8 -*-

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol

import smtplib
import logging

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
    "hugopl",
    "igoroliveira",
    "jeez_",
    "lmoura",
    "luck",
    "rafaelbrandao",
    "setanta",
    "jprvita",

    "bbandix",
    "elproxy",
    "jturcotte",
    "kling",
    "torarne",
    "tronical",
    "zalbisser",

    "ahf",
    "kenneth_",
    "laknudse",
    "mibrunin",
    "mulvad",
    "zalan",

    "Ossy",
    "Smith",
    "TwistO",
    "Zoltan",
    "andris88",
    "azbest_hu",
    "kbalazs",
    "kkristof",
    "loki04",
    "reni",
    "tczene",
    "zherczeg",
    ]

SMTP = "smtp.gmail.com"
FROM = "Qt WebKit StatusBot <qtwebkit-statusbot@openbossa.org>"
TO = "webkit-qt@lists.webkit.org"
# TO = "caio.oliveira@openbossa.org"

MEETING_TIME_IN_SECONDS = 60 * 60
#MEETING_TIME_IN_SECONDS = 0.5 * 60

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
        self.factory.missing_participants.clear()
        self.factory.status_messages.clear()

    def _register_status_message(self, nickname, message):
        if not self.factory.ongoing:
            return
        logging.warning("Adding status message from '%s': %s" % (nickname, message))
        self.factory.status_messages[nickname] = message
        self.factory.missing_participants.discard(nickname)
        if nickname.endswith('_'):
            self.factory.missing_participants.discard(nickname[:-1])

    def alterCollidedNick(self, nickname):
        logging.warning("Nick Collision")
        self.factory.nickname = nickname + '_'
        return self.factory.nickname

    def signedOn(self):
        logging.warning("Joining Channel: %s" % self.factory.channel)
        self.join(self.factory.channel)

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
        self.factory.missing_participants = set(self.factory.people)
        self.describe(channel, "*pokes* %s" % self._missing_participants_sorted())

        reactor.callLater(MEETING_TIME_IN_SECONDS / 2, self._remind_missing_participants)
        reactor.callLater(MEETING_TIME_IN_SECONDS, self._end_meeting)

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

    def __init__(self, nickname, channel, people):
        self.nickname = nickname
        self.channel = channel
        self.people = people
        # FIXME: These properties are here in case the connection drop, but I don't think we
        # actually recover from that. Code would be simpler if they were not here.
        self.missing_participants = set()
        self.status_messages = {}
        self.ongoing = False

    def clientConnectionLost(self, connector, reason):
        logging.warning("Connection Lost: %s" % reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        logging.warning("Connection Lost: %s" % reason)
        reactor.callLater(600, connector.connect)

if "__main__" == __name__:
    bot = StatusBotClientFactory(NICK, CHANNEL, PEOPLE)
    logging.warning("Trying to connect to " + SERVER)
    reactor.connectTCP(SERVER, PORT, bot)
    reactor.run()

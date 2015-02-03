#!/usr/bin/env python
# -*- coding: utf-8 -*-

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from datetime import datetime, time, timedelta
from unidecode import unidecode

import os, sys, random
import logging

sys.path.insert(0, 'py-trello')
from trello import TrelloClient

NICK = "Qtrello"
SERVER = "chat.freenode.net"
PORT = 8001
CHANNEL = "#qtwebengine"
BOARD_ID = "5G9c1rkb"

# This currently assumes that the board is public, this bot does read-only operations only.
trello = TrelloClient(api_key=None)

def parse_trello_date(str_date):
    return datetime.strptime(str_date, "%Y-%m-%dT%H:%M:%S.%fZ")

def friday_meeting_delta():
    MEETING_HOUR = (15, 00)
    meeting_time = time(*MEETING_HOUR)
    today = datetime.today()
    days_ahead = 4 - today.weekday()
    is_after_meeting = today.hour > meeting_time.hour or \
                       (today.hour == meeting_time.hour and today.minute >= meeting_time.minute)
    if days_ahead < 0 or (days_ahead == 0 and is_after_meeting):
        days_ahead += 7
    friday = today + timedelta(days_ahead)
    friday_meeting = datetime.combine(friday, meeting_time)
    return friday_meeting - datetime.now()

def fetch_card_shorturl(trello, card_id):
    return trello.fetch_json('/cards/' + card_id + '/shortUrl')['_value']

def fetch_open_lists(trello, board_id):
    return trello.fetch_json(
        '/boards/' + board_id + '/lists',
        query_params={'cards': 'none', 'filter': 'open'})

def fetch_list_cards(trello, list_id):
    """Lists all cards in this list"""
    return trello.fetch_json('/lists/' + list_id + '/cards')

def fetch_card_last_action_datetime(trello, card_id):
    actions = trello.fetch_json(
        '/cards/' + card_id + '/actions',
        query_params={'fields': 'date', 'format': 'list', 'count': 1, 'filter': 'addAttachmentToCard,addChecklistToCard,commentCard,updateCard,updateCheckItemStateOnCard,updateChecklist'})
    if (len(actions)):
        return parse_trello_date(actions[0]['date'])

def fetch_board_progress_actions(trello, board_id, since):
    return trello.fetch_json(
        '/boards/' + board_id + '/actions',
        query_params={'filter': 'updateCard,updateCheckItemStateOnCard', 'limit': 100, 'fields': 'type,data,date', 'since': since})

def fetch_immediate_board_actions(trello, board_id, since):
    return trello.fetch_json(
        '/boards/' + board_id + '/actions',
        query_params={'filter': 'commentCard,createCard', 'limit': 10, 'fields': 'type,data,date', 'memberCreator_fields': 'fullName,username', 'since': since})


class TrelloBotClient(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname

    nickname = property(_get_nickname)
    lineRate = 2

    def __init__(self):
        self.real_to_nick = {}

    def find_nick(self, trello_realname, trello_username):
        return self.real_to_nick.get(unidecode(trello_realname), trello_username)

    def fetch_realnames(self):
        channel = self.factory.channel
        self.real_to_nick = {}
        self.sendLine("WHO " + channel)

        # Update every hour
        reactor.callLater(timedelta(hours=1).total_seconds(), self.fetch_realnames)

    def irc_RPL_WHOREPLY(self, prefix, params):
        # Remove the first two characters, the hopcount get parsed into the realname array index
        # Assume that names are in Latin-1
        realname = unidecode(unicode(params[-1][2:], "iso-8859-1"))
        nickname = params[-3]
        self.real_to_nick[realname] = nickname

    def alterCollidedNick(self, nickname):
        logging.warning("Nick Collision")
        self.factory.nickname = nickname + '_'
        return self.factory.nickname

    def signedOn(self):
        logging.warning("Joining Channel: %s" % self.factory.channel)
        self.join(self.factory.channel)

        timeleft = friday_meeting_delta()
        reactor.callLater(timeleft.total_seconds(), self._weekly_card_report)
        reactor.callLater(10, self._report_activity)
        logging.warning("Time left until the report: %s" % (timeleft))

    def joined(self, channel):
        self.fetch_realnames()

    def describe_action(self, a):
        irc_nick = self.find_nick(a['memberCreator']['fullName'], a['memberCreator']['username'])
        card_name = a['data']['card']['name']
        if a['type'] == 'createCard':
            card_url = fetch_card_shorturl(trello, a['data']['card']['id'])
            return str('%s created [ \x02%s\x02 ] <%s>' % (irc_nick, card_name, card_url))
        elif a['type'] == 'commentCard':
            text = a['data']['text']
            if len(text) > 100:
                text = text[:97] + '...'
            card_url = fetch_card_shorturl(trello, a['data']['card']['id'])
            return str('%s commented: "\x02%s\x02" on [ %s ] <%s>' % (irc_nick, text, card_name, card_url))
        elif a["type"] == 'updateCard' and 'listAfter' in a['data']:
            list_name = a['data']['listAfter']['name']
            card_url = 'https://trello.com/c/' + a['data']['card']['shortLink']
            return str('%s moved [ \x02%s\x02 ] to "%s" <%s>' % (irc_nick, card_name, list_name, card_url))
        elif a["type"] == 'updateCheckItemStateOnCard':
            card_url = 'https://trello.com/c/' + a['data']['card']['shortLink']
            check_item_name = a['data']['checkItem']['name']
            return str('%s completed "\x02%s\x02" on [ %s ] <%s>' % (irc_nick, check_item_name, card_name, card_url))

    def _report_activity(self):
        channel = self.factory.channel
        actions = fetch_immediate_board_actions(trello, BOARD_ID, self.factory.last_notified_action_date)
        if (len(actions)):
            self.factory.last_notified_action_date = actions[0]['date']

        for a in actions:
            self.notice(channel, self.describe_action(a))

        # Check again in 1 minute
        reactor.callLater(60, self._report_activity)

    def _weekly_card_report(self):
        channel = self.factory.channel
        doing_list = None
        for l in fetch_open_lists(trello, BOARD_ID):
            if l['name'] == "Doing":
                doing_list = l

        self.describe(channel, "begins the weekly report")

        doingHeaderSent = False
        def ensureDoingHeaderSent(alreadyDidIt):
            if not alreadyDidIt:
                self.describe(channel, "starts listing cards in Doing that haven't been updated in the last two weeks.")
            return True

        for c in fetch_list_cards(trello, doing_list['id']):
            last_action_datetime = fetch_card_last_action_datetime(trello, c['id'])
            if not last_action_datetime:
                last_action_datetime = parse_trello_date(c['dateLastActivity'])
            last_action_delta = datetime.utcnow() - last_action_datetime
            if last_action_delta > timedelta(weeks=2):
                assigned = []
                for mId in c['idMembers']:
                    m = trello.get_member(mId)
                    assigned.append(self.find_nick(m.full_name, m.username))
                card_url = 'https://trello.com/c/' + c['shortLink']
                doingHeaderSent = ensureDoingHeaderSent(doingHeaderSent)
                self.say(channel, str("%d days ago: [ \x02%s\x02 ] assigned to [%s]. <%s>" % (last_action_delta.days, c['name'], ', '.join(assigned), card_url)))

        progressHeaderSent = False
        def ensureProgressHeaderSent(alreadyDidIt):
            if not alreadyDidIt:
                self.describe(channel, "starts reporting cards that progressed since last week.")
            return True

        # Pick the first (most recent) action for each card/checkItem to make sure
        # that we report the current state.
        move_to_list_actions = {}
        check_item_completed_actions = {}
        a_week_ago = datetime.utcnow() - timedelta(weeks=1)
        for a in fetch_board_progress_actions(trello, BOARD_ID, a_week_ago.isoformat()):
            if a["type"] == 'updateCard' and 'listAfter' in a['data']:
                if not a['data']['card']['id'] in move_to_list_actions:
                    move_to_list_actions[a['data']['card']['id']] = a
            elif a["type"] == 'updateCheckItemStateOnCard':
                if not a['data']['checkItem']['id'] in check_item_completed_actions:
                    check_item_completed_actions[a['data']['checkItem']['id']] = a

        for a in move_to_list_actions.values():
            list_name = a['data']['listAfter']['name']
            if list_name.startswith('Done'):
                progressHeaderSent = ensureProgressHeaderSent(progressHeaderSent)
                self.say(channel, self.describe_action(a))

        for a in check_item_completed_actions.values():
            if a['data']['checkItem']['state'] == 'complete':
                progressHeaderSent = ensureProgressHeaderSent(progressHeaderSent)
                self.say(channel, self.describe_action(a))

        self.describe(channel, "is done with the report, thank you!")
        # Report again in one week
        reactor.callLater(timedelta(weeks=1).total_seconds(), self._weekly_card_report)

    def privmsg(self, hostmask, channel, message):
        # An IRC hostmask is on the form "nick!user@hostname".
        user_nickname = hostmask.split('!')[0]
        if self.nickname in message:
            self.say(channel, "%s %s" % (random.choice(['Hello', 'Hi']), user_nickname))


class TrelloBotClientFactory(protocol.ClientFactory):
    protocol = TrelloBotClient

    def __init__(self, nickname, channel):
        self.nickname = nickname
        self.channel = channel
        self.last_notified_action_date = datetime.utcnow().isoformat()

    def clientConnectionLost(self, connector, reason):
        logging.warning("Connection Lost: %s" % reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        logging.warning("Connection Lost: %s" % reason)
        reactor.callLater(600, connector.connect)


if "__main__" == __name__:
    bot = TrelloBotClientFactory(NICK, CHANNEL)
    logging.warning("Trying to connect to " + SERVER)
    reactor.connectTCP(SERVER, PORT, bot)
    reactor.run()

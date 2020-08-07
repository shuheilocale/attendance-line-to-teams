# -*- coding: utf-8 -*-
import sys
import os
import logging
import json
import random
import string
import urllib

from flask import Flask, request, abort, render_template, jsonify

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
)

from google.appengine.ext import ndb

from google.appengine.api import urlfetch
urlfetch.set_default_fetch_deadline(60)


class Attendance(ndb.Model):
    u_key = ndb.StringProperty()
    user_id = ndb.StringProperty()
    approval = ndb.BooleanProperty()

class UserName(ndb.Model):
    user_id = ndb.StringProperty()
    user_name = ndb.StringProperty()


def random_name(n):
    randlst = [random.choice(string.ascii_letters + string.digits)
               for i in range(n)]
    return ''.join(randlst)


def to_utf8(params):

    if type(params) is list:
        str_params = []
        for v in params:
            if type(v) is list or type(v) is dict:
                v = to_utf8(v)
            else:
                v = unicode(v).encode('utf-8')
            str_params.append(v)

    elif type(params) is dict:
        str_params = {}
        for k, v in params.items():
            if type(v) is list or type(v) is dict:
                v = to_utf8(v)
            else:
                v = unicode(v).encode('utf-8')
            str_params[k] = v
    return str_params


app = Flask(__name__)

channel_access_token = os.getenv('CHANNEL_ACCESS_TOKEN', None)
channel_secret = os.getenv('CHANNEL_SECRET', None)

if channel_secret is None:
    app.logger.critical('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    app.logger.critical(
        'Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)


@app.route('/')
def hello():
    return 'hello world.'


@app.route('/callback', methods=['POST'])
def callback():

    signature = request.headers['X-Line-Signature']

    body = request.get_data(as_text=True)
    logging.info('Request body: ' + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@app.route('/form')
def form():
    return render_template('form.html')

@app.route('/username', methods=['POST'])
def username():
    logging.info(request.form)
    user_id = request.form['userId']
    un = UserName.query(UserName.user_id == user_id).get()
    logging.info('username', un)
    if un is None:
        return ''
    return un.user_name

@app.route('/accept')
def accept():
    key = request.args.get('k')
    attendance = Attendance.query(Attendance.u_key == key).get()
    logging.info(attendance.user_id)
    if attendance.approval is True:
        return u'すでに確認しています。'

    attendance.approval = True
    attendance.put()

    messages = TextSendMessage(text=u'確認されました。')
    line_bot_api.push_message(attendance.user_id, messages=messages)

    return u'確認しました。'


@app.route('/replyacc', methods=['POST'])
def replyacc():
    logging.info(request.json)

    key = request.json['ukey']
    if 'comment' in request.json:
        comment = request.json['comment']
    else:
        comment = ""

    attendance = Attendance.query(Attendance.u_key == key).get()
    logging.info(attendance)
    if attendance.approval is True:
        return jsonify({'success': True})

    attendance.approval = True
    attendance.put()

    if comment == "":
        messages = TextSendMessage(text=u'確認されました。')
    else:
        messages = TextSendMessage(text=u'確認されました。\n\n【コメント】 \n\n' + comment)

    line_bot_api.push_message(attendance.user_id, messages=messages)

    response = jsonify({'success': True})
    headers = to_utf8({'ContentType': 'application/json',
                       'CARD-ACTION-STATUS': 'OK!'})
    response.headers = headers
    response.status_code = 200

    return response


@app.route('/sendteams', methods=['POST'])
def sendteams():

    logging.info(request.form)
    name = request.form['name']
    date = request.form['date']
    kind = request.form['kind']
    detail = request.form['detail']
    user_id = request.form['userId']

    u_key = random_name(10)

    attendance = Attendance(u_key=u_key, user_id=user_id, approval=False)
    attendance.put()

    un = UserName.query(UserName.user_id == user_id).get()
    if un is None:
        un = UserName(user_id=user_id, user_name=name)
    else:
        un.user_name=name
    un.put()

    title = u'{} {} {}'.format(name, date, kind)

    if kind == u'全休':
        img = 'zenkyu.png'
    elif kind == u'午前休':
        img = 'gozenkyu.png'
    elif kind == u'午後休':
        img = 'gogokyu.png'
    elif kind == u'遅れ':
        img = 'okure.png'
    elif kind == u'フレックス':
        img = 'flex.png'
    else:
        img = 'zenkyu.png'

    params = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "0076D7",
        "summary": title,
        "sections": [{
            "activityTitle": title,
            "activityImage": os.getenv('HOME_URL', None) + "static/" + img,
            "facts": [{
                "name": u"詳細",
                "value": detail
            }],
            "markdown": "true"
        }],
        "potentialAction": [{
            "@type": "ActionCard",
            "name": "accept",
            "inputs": [
                {
                    "@type": "TextInput",
                    "id": "comment",
                    "isMultiline": "true",
                    "title": u"申請者へコメント送る場合はここに記入してください。"
                }
            ],
            "actions": [{
                "@type": "HttpPOST",
                "name": u"確認通知を送る",
                "target": os.getenv('HOME_URL', None) + "replyacc",
                "body": "{{\"ukey\":\"{}\",\"comment\":\"{{{{comment.value}}}}\"}}".format(u_key)
            }]
        }]
    }

    str_params = to_utf8(params)
    webhook_url = os.getenv('WEBHOOK_URL')
    webhook_url_sub = os.getenv('WEBHOOK_URL_SUB')
    send_error_flag = False
    send_sub_flag = False
    try:
        payload = json.dumps(str_params)
        logging.info(payload)
        headers = {'Content-Type': 'application/json'}
        result = urlfetch.fetch(
            url=webhook_url,
            payload=payload,
            method=urlfetch.POST,
            headers=headers)
        if result.status_code == 200:
            logging.info(result.content)

            # 正常メッセージ(1)でなければ、サブURLに通知する
            if result.content != "1":
                send_sub_flag = True
                logging.info("try webhook url sub")
                result = urlfetch.fetch(
                    url=webhook_url_sub,
                    payload=payload,
                    method=urlfetch.POST,
                    headers=headers)

                if result.status_code == 200:
                    logging.info(result.content)

                    # サブでも正常メッセージ(1)でなければ、エラーを返す
                    if result.content != "1":
                        send_error_flag = True

                else:
                    logging.error(result.content)
                    return json.dumps({'success': False}), 500, {'ContentType': 'application/json'}

        else:
            logging.error(result.content)
            return json.dumps({'success': False}), 500, {'ContentType': 'application/json'}
    except urlfetch.Error:
        logging.exception('Caught exception fetching url')
        return json.dumps({'success': False}), 500, {'ContentType': 'application/json'}

    if send_error_flag:
        messages = TextSendMessage(
            text=u'提出に失敗しました。他の手段で連絡してください。\n\n{} {} {}\n{}'.format(name, date, kind, detail))
    elif send_sub_flag:
        messages = TextSendMessage(
            text=u'メインチームへの提出に失敗したので、他のチームに提出しました。\n\n{} {} {}\n{}'.format(name, date, kind, detail))
    else:
        messages = TextSendMessage(
            text=u'提出しました。\n\n{} {} {}\n{}'.format(name, date, kind, detail))

    line_bot_api.push_message(user_id, messages=messages)

    return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    logging.info(event)

    if event.message.text == u'勤怠':
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=os.getenv('LIFF_URL')))


if __name__ == '__main__':
    # app.run()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

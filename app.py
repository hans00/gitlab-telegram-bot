#!/usr/bin/env python3

import os
import json
import logging
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    g
)
from teleflask import Teleflask
from teleflask.messages import MarkdownMessage
from hashlib import sha1
import dataset
import shlex
import random

app = Flask(__name__)
bot = Teleflask(os.environ.get('TG_TOKEN'), app)

DATABASE_URL = os.environ.get('DATABASE_URL', "sqlite:///data.db")

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = dataset.connect(DATABASE_URL)
    return db

def init_db():
    with app.app_context():
        db = get_db()
        db.create_table(
            'repos',
            primary_id='token',
            primary_type=db.types.string(40)
            )
        db['repos'].create_column('name', db.types.text)
        db['repos'].create_column('url', db.types.text)
        db.create_table('chats')
        db['chats'].create_column('token', db.types.string(40))
        db['chats'].create_column('chat_id', db.types.bigint)
        db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.commit()

@bot.on_startup
def startup():
    db = get_db()
    msg = "大家好，台灣最大的 GitLab 機器人上線啦。"
    for chat in db['chats'].all():
        bot.send_message(MarkdownMessage(msg), chat['chat_id'], None)

@bot.on_message
def msg_me(update, msg):
    if msg.text.startswith('/'):
        pass
    else:
        return MarkdownMessage("我不會講話，所以不要跟我說話。")

@bot.command("start")
def start(update, text):
    return MarkdownMessage("*泥郝* 歡迎使用 @" + bot.username.replace('_', '\_'))

@bot.command("help")
def ping(update, text):
    help_text  = "/help - this message\n"
    help_text += "/ping - ping bot\n"
    help_text += "/reg <token> - bind repo\n"
    help_text += "/bye [token] - unbind repo\n"
    leading_message = [
        "你以為我會給你提示ㄇ (?\n\n\n\n\n\n對我會\n\n",
        "我才不會幫助你呢 (X\n\n\n\n",
    ]
    return MarkdownMessage(random.choice(leading_message)+help_text)

@bot.command("ping")
def ping(update, text):
    return MarkdownMessage("pong")

@bot.command("reg")
def reg(update, text):
    if not text:
        return MarkdownMessage("Usage: /reg <token>")
    else:
        args = shlex.split(text)
        token = args[0]
        db = get_db()
        result = db['repos'].find_one(token=token)
        if update.message.chat:  # is a group chat
            sender = update.message.chat.id
        else:  # user chat
            sender = update.message.from_peer.id
        if len(result) > 0:
            if not db['chats'].find_one(token=token, chat_id=sender):
                db['chats'].insert(dict(token=token, chat_id=sender))
                return MarkdownMessage("\U0001F60E Yey! It's works.")
            else:
                return MarkdownMessage("重複綁定")
        else:
            return MarkdownMessage("Not exists token!")

@bot.command("bye")
def bye(update, text):
    db = get_db()
    if update.message.chat:  # is a group chat
        sender = update.message.chat.id
    else:  # user chat
        sender = update.message.from_peer.id
    bind_count = db['chats'].count(chat_id=sender)
    if bind_count == 0:
        return MarkdownMessage("你未曾綁定過任何專案唷")
    if bind_count == 1:
        db['chats'].delete(chat_id=sender)
        return MarkdownMessage("\U0001F63F 好吧\n掰掰")
    elif not text:
        repo_list = "`token` - *專案名稱*"
        for bind in binds:
            repo = db['repos'].find_one(token=bind['token'])
            repo_list += "`%s` - *%s*\n" % (repo.token, repo['name'].replace('*', '\*'))
        return MarkdownMessage("找到有綁定多個專案，請指定。\n使用方法： /bye <token>\n"+repo_list)
    else:
        args = shlex.split(text)
        token = args[0]
        if db['chats'].find_one(chat_id=sender, token=token):
            db['chats'].delete(chat_id=sender, token=token)
            return MarkdownMessage("\U0001F63F 好吧\n掰掰")
        else:
            return MarkdownMessage("呃... 你似乎沒綁定過這個")

@app.route("/", methods=['GET'])
def index():
    db = get_db()
    repos = db['repos'].all()
    return render_template('index.html', repos=repos)

@app.route("/register", methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    else:
        db = get_db()
        name = request.form['name']
        url  = request.form['url']
        if name == '' and url == '':
            return render_template('register_done.html', success=False)
        else:
            token = sha1(url.encode('utf8')).hexdigest()
            db['repos'].insert(dict(token=token, name=name, url=url))
            base_url = '/'.join(bot.webhook_url.split("/")[:3])
            return render_template('register_done.html', success=True, token=token, base_url=base_url, bot_username=bot.username)

@app.route("/gitlab/", methods=['GET', 'POST'])
def gitlab_webhook():
    if request.method == 'POST':
        token = request.headers.get('X-Gitlab-Token')
        db = get_db()
        if not db['repos'].count(token=token):
            return jsonify({'status':'bad token'}), 401
        else:
            chats = db['chats'].find(token=token)
        data = request.json
        # json contains an attribute that differenciates between the types, see
        # https://docs.gitlab.com/ce/user/project/integrations/webhooks.html
        # for more infos
        kind = data['object_kind']
        if kind == 'push':
            msg = generatePushMsg(data)
        elif kind == 'tag_push':
            msg = generatePushMsg(data)  # TODO:Make own function for this
        elif kind == 'issue':
            msg = generateIssueMsg(data)
        elif kind == 'note':
            msg = generateCommentMsg(data)
        elif kind == 'merge_request':
            msg = generateMergeRequestMsg(data)
        elif kind == 'wiki_page':
            msg = generateWikiMsg(data)
        elif kind == 'pipeline':
            msg = generatePipelineMsg(data)
        elif kind == 'build':
            msg = generateBuildMsg(data)
        else:
            msg = 'ERROR: `unknown_event`'
        for chat in chats:
            bot.send_message(MarkdownMessage(msg), chat['chat_id'], None)
        return jsonify({'status': 'ok'}), 200
    else:
        return jsonify({'status':'invalid request'}), 400


def generatePushMsg(data):
    msg = '*{0} ({1}) - {2} new commits*\n'\
        .format(data['project']['name'], data['project']['default_branch'], data['total_commits_count'])
    for commit in data['commits']:
        msg = msg + '----------------------------------------------------------------\n'
        msg = msg + commit['message'].rstrip()
        msg = msg + '\n' + commit['url'].replace("_", "\_") + '\n'
    msg = msg + '----------------------------------------------------------------\n'
    return msg


def generateIssueMsg(data):
    action = data['object_attributes']['action']
    if action == 'open':
        msg = '*{0} new Issue for {1}*\n'\
            .format(data['project']['name'], data['assignee']['name'])
    elif action == 'close':
        msg = '*{0} Issue closed by {1}*\n'\
            .format(data['project']['name'], data['user']['name'])
    msg = msg + '*{0}*'.format(data['object_attributes']['title'])
    msg = msg + 'see {0} for further details'.format(data['object_attributes']['url'])
    return msg


def generateCommentMsg(data):
    ntype = data['object_attributes']['noteable_type']
    if ntype == 'Commit':
        msg = 'note to commit'
    elif ntype == 'MergeRequest':
        msg = 'note to MergeRequest'
    elif ntype == 'Issue':
        msg = 'note to Issue'
    elif ntype == 'Snippet':
        msg = 'note on code snippet'
    return msg


def generateMergeRequestMsg(data):
    return 'new MergeRequest'

def generateWikiMsg(data):
    return 'new wiki stuff'

def generatePipelineMsg(data):
    return 'new pipeline stuff'

def generateBuildMsg(data):
    return 'new build stuff'

if __name__ == "__main__":
    init_db()
    app.run()

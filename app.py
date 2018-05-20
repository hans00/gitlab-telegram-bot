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
import requests
import dataset
import shlex
import random
import re
from distutils.version import StrictVersion

__version__  = '0.2.0'

app = Flask(__name__)
bot = Teleflask(os.environ.get('TG_TOKEN'), app)

DATABASE_URL = os.environ.get('DATABASE_URL', "sqlite:///data.db")

url_regex = re.compile(r"^(https?:\/\/[\w\-\.]+\.[a-z]{2,20}\/[\w\-]+\/[\w\-]+)$", re.I)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = dataset.connect(DATABASE_URL)
    return db

def init_db():
    with app.app_context():
        db = get_db()
        fresh_db = False
        if len(db.tables) == 0:
            fresh_db = True
        elif StrictVersion(db['meta_data'].find_one(key='version')['value']) < StrictVersion(__version__):
            for table in db.tables:
                db[table].drop()
            fresh_db = True
        if fresh_db:
            db.create_table(
                'meta_data',
                primary_id='key',
                primary_type=db.types.string(20)
                )
            db['meta_data'].create_column('colunm', db.types.text)
            db['meta_data'].insert(dict(key='version', value=str(__version__)))
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

def is_group(update):
    return True if update.message.chat else False

def get_id(update):
    if is_group(update):  # is a group chat
        return update.message.chat.id
    else:  # user chat
        return update.message.from_peer.id

def is_tag_bot(update):
    if len(update.message.entities) == 0:
        return False
    else:
        for entity in update.message.entities:
            if entity.type == 'mention' and entity.user == bot.username:
                return True
        return False

def check_url(url):
    return requests.get(url).text.find('GitLab') != -1

def markdown_escape(data):
    return data.replace("_", "\_").replace("*", "\*")

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.commit()

@bot.on_startup
def bot_started():
    db = get_db()
    msg = "大家好，台灣最大的 GitLab 機器人上線啦。"
    for chat in db['chats'].all():
        bot.send_message(MarkdownMessage(msg), chat['chat_id'], None)

@bot.on_message
def msg_me(update, msg):
    if msg.text.startswith('/'):
        pass
    elif not is_group(update) or is_tag_bot(update):
        return MarkdownMessage("我不會講話，所以不要跟我說話。")

@bot.command("start")
def start(update, text):
    return MarkdownMessage("*Hello World*\n歡迎使用 @" + markdown_escape(bot.username))

@bot.command("help")
def ping(update, text):
    help_text  = "/help - this message\n"
    help_text += "/ping - ping bot\n"
    help_text += "/reg <token> - bind repo\n"
    help_text += "/bye \[token\] - unbind repo\n"
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
        sender = get_id(update)
        if db['repos'].count(token=token) > 0:
            if db['chats'].count(token=token, chat_id=sender) == 0:
                db['chats'].insert(dict(token=token, chat_id=sender))
                return MarkdownMessage("\U0001F60E Yey! It's works.")
            else:
                return MarkdownMessage("重複綁定")
        else:
            return MarkdownMessage("Not exists token!")

@bot.command("bye")
def bye(update, text):
    db = get_db()
    sender = get_id(update)
    bind_count = db['chats'].count(chat_id=sender)
    if bind_count == 0:
        return MarkdownMessage("你未曾綁定過任何專案唷")
    if bind_count == 1:
        db['chats'].delete(chat_id=sender)
        return MarkdownMessage("\U0001F63F 好吧\n掰掰")
    elif not text:
        repo_list = "`token` - *專案名稱*"
        for bind in db['chats'].find(chat_id=sender):
            repo = db['repos'].find_one(token=bind['token'])
            repo_list += "`%s` - *%s*\n" % (repo.token, markdown_escape(repo['name']))
        return MarkdownMessage("找到有綁定多個專案，請指定。\n使用方法： /bye <token>\n"+repo_list)
    else:
        args = shlex.split(text)
        token = args[0]
        if db['chats'].count(chat_id=sender, token=token):
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
        name  = request.form.get('name', type=str, default='')
        url   = request.form.get('url', type=str, default='')
        token = sha1(url.encode('utf8')).hexdigest()
        exists = db['repos'].count(token=token)
        if name != '' and url != '' and exists == 0 and url_regex.match(url) and check_url(url):
            db['repos'].insert(dict(token=token, name=name, url=url))
            base_url = '/'.join(bot.webhook_url.split("/")[:3])
            return render_template('register_done.html', success=True, token=token, base_url=base_url, bot_username=bot.username)
        else:
            return render_template('register_done.html', success=False)

@app.route("/gitlab/", methods=['GET', 'POST'])
def gitlab_webhook():
    if request.method == 'POST':
        token = request.headers.get('X-Gitlab-Token')
        db = get_db()
        if not db['repos'].count(token=token):
            return jsonify({'status':'bad token'}), 401
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
        if msg is not None:
            chats = db['chats'].find(token=token)
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
        msg = msg + markdown_escape(commit['message'].rstrip())
        msg = msg + '\n' + markdown_escape(commit['url']) + '\n'
    msg = msg + '----------------------------------------------------------------\n'
    return msg


def generateIssueMsg(data):
    action = data['object_attributes']['action']
    if action == 'open':
        msg = '*{0} new Issue for {1}*\n'\
            .format(markdown_escape(data['project']['name']), markdown_escape(data['assignee']['name']))
    elif action == 'close':
        msg = '*{0} Issue closed by {1}*\n'\
            .format(markdown_escape(data['project']['name']), markdown_escape(data['user']['name']))
    msg = msg + '*{0}*'.format(markdown_escape(data['object_attributes']['title']))
    msg = msg + 'see {0} for further details'.format(markdown_escape(data['object_attributes']['url']))
    return msg


def generateCommentMsg(data):
    ntype = data['object_attributes']['noteable_type']
    if ntype == 'Commit':
        msg = '*Comment commit on {project}*\n{hr}\n{note}\n{url}'\
        .format(
            project=markdown_escape(data['project']['path_with_namespace']),
            hr="----------------------------------------------------------------",
            note=markdown_escape(data['object_attributes']['note']),
            url=markdown_escape(data['object_attributes']['url'])
            )
    elif ntype == 'MergeRequest':
        msg = '*Comment merge request on {project}!{mr_id}*\n{hr}\n*{title}*\n{note}\n{url}'\
        .format(
            project=markdown_escape(data['project']['path_with_namespace']),
            url=markdown_escape(data['object_attributes']['url']),
            mr_id=data['merge_request']['id'],
            hr="----------------------------------------------------------------",
            title=markdown_escape(data['merge_request']['title']),
            note=markdown_escape(data['object_attributes']['note'])
            )
    elif ntype == 'Issue':
        msg = '*Comment issue on {project}#{issue_id}*\n{hr}\n*{title}*\n{note}\n{url}'\
        .format(
            project=markdown_escape(data['project']['path_with_namespace']),
            url=markdown_escape(data['object_attributes']['url']),
            issue_id=data['issue']['id'],
            hr="----------------------------------------------------------------",
            title=markdown_escape(data['issue']['title']),
            note=markdown_escape(data['object_attributes']['note'])
            )
    elif ntype == 'Snippet':
        msg = '*Comment snippet on {project}/{snippet_id}*\n{hr}\n*{title}*\n{note}\n{url}'\
        .format(
            project=markdown_escape(data['project']['path_with_namespace']),
            url=markdown_escape(data['object_attributes']['url']),
            snippet_id=data['snippet']['id'],
            hr="----------------------------------------------------------------",
            title=markdown_escape(data['snippet']['title']),
            note=markdown_escape(data['object_attributes']['note'])
            )
    return msg


def generateMergeRequestMsg(data):
    action = data['object_attributes']['action']
    if action in ['open', 'close']:
        msg = "*{project_name} {state} Merge Request*\nfrom *{source}* to *{target}*\n\n*{title}*\n{description}"\
        .format(
            project_name=markdown_escape(data['project']['name']),
            state=data['object_attributes']['state'],
            title=markdown_escape(data['object_attributes']['title']),
            source=markdown_escape(data['object_attributes']['source']['path_with_namespace']+':'+data['object_attributes']['source_branch']),
            target=markdown_escape(data['object_attributes']['target']['path_with_namespace']+':'+data['object_attributes']['target_branch']),
            description=markdown_escape(data['object_attributes']['description'])
            )
    else:
        msg = None
    return msg

def generateWikiMsg(data):
    return None

def generatePipelineMsg(data):
    return None

def generateBuildMsg(data):
    return "*{project_name} build on {build_stage}:{build_name} {build_state}*\n{hr}\n{message}\n{author_name}<{author_email}>"\
    .format(
        project_name=markdown_escape(data['project_name']),
        build_state=data['build_state'],
        build_stage=data['build_stage'],
        build_name=markdown_escape(data['build_name']),
        hr="----------------------------------------------------------------",
        message=markdown_escape(data['commit']['message'].rstrip()),
        author_name=markdown_escape(data['commit']['author_name']),
        author_email=markdown_escape(data['commit']['author_email'])
        )

if __name__ == "__main__":
    init_db()
    app.run()

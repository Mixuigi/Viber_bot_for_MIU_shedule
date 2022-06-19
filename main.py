import requests
import sqlite3
import imgkit
import base64
import random
import string
import time
import os

from bs4 import BeautifulSoup
from conf import TOKEN
from flask import Flask, request, Response, send_from_directory
from viberbot import Api
from viberbot.api.bot_configuration import BotConfiguration
from viberbot.api.messages import PictureMessage, KeyboardMessage, RichMediaMessage, FileMessage
from viberbot.api.messages.text_message import TextMessage
import logging

from viberbot.api.viber_requests import ViberConversationStartedRequest
from viberbot.api.viber_requests import ViberFailedRequest
from viberbot.api.viber_requests import ViberMessageRequest
from viberbot.api.viber_requests import ViberSubscribedRequest
from viberbot.api.viber_requests import ViberUnsubscribedRequest

from buttons import WEEK_KEYBOARD

SITE_URL = 'http://www.miu.by/rus/schedule/schedule.php'
URL_FOR_SHEDULE = 'http://miu.by/rus/schedule/shedule_load.php'
HEADERS_FOR_SHEDULE = {
    "Host": "www.miu.by",
    "Connection": "keep-alive",
    "User-Agent": "PostmanRuntime/7.28.3",
    "Content-type": "application/x-www-form-urlencoded",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
}

HEADERS_FOR_PARSE = {
    'User-Agent': 'Mozilla/5.0'
}
current_timestamp = []
app = Flask(__name__, static_url_path='/static')
viber = Api(BotConfiguration(
    name='MIU Bot',
    avatar='',
    auth_token=TOKEN
))

database = sqlite3.connect('TelegramData.db', check_same_thread=False)
cur = database.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS tgdata
               (tgid integer , miuGroup text)''')
database.commit()

ngrok_http = 'https://abfe-37-214-73-148.eu.ngrok.io'


def delete_data_sql(viber_request):
    cur.execute(f"DELETE FROM tgdata WHERE tgid = '{viber_request.sender.id}'")
    database.commit()


def write_data_in_db(viber_request, text):
    delete_data_sql(viber_request)
    cur.execute(f"INSERT INTO tgdata VALUES(?, ?)", (viber_request.sender.id, text))
    database.commit()


def get_number_this_week():
    html = requests.get(SITE_URL, headers=HEADERS_FOR_PARSE)
    soup = BeautifulSoup(html.content, 'html.parser')
    string_with_number_week = soup.select('#printpage > span:nth-child(6)')[0]
    return int(string_with_number_week.text.split(' ')[-1])


def get_site_html(message, data, type_data, number_week):
    if message is True:
        pass
    else:
        data = message
    return requests.post(
        URL_FOR_SHEDULE,
        headers=HEADERS_FOR_SHEDULE,
        data={'week': number_week, type_data: data},
    )


def generate_random_str():
    for i in range(6):
        # get random string of length 6 without repeating letters
        word = ''.join(random.sample(string.ascii_lowercase, 8))
        return word


def parse_web_site(data, number_week):
    if any(map(str.isdigit, data)):
        type_data = 'group'
    else:
        type_data = 'prep'
    # number_week = 25
    message = True
    html = get_site_html(message, data, type_data, number_week)
    if html.ok:
        schedule = html.text.split('<br>')[1]
        schedule = schedule[:72] + 'zoom:220%;' + schedule[72:]
        return imgkit.from_string(schedule, False)



def search_suggestions_buttons(links):
    buttons = []
    for link in links:
        button = {
        "Columns": 3,
        "Rows": 1,
        "Text": f"<b><font color=\"#ffffff\">{link}</font></b>",
        "TextSize": "large",
        "TextHAlign": "center",
        "TextVAlign": "center",
        "ActionType": "reply",
        "ActionBody": f"{link}",
        "BgColor": "#7b58b0",
        "Silent": True,
    }
        buttons.append(button)
    return {
        "Type": "keyboard",
        "Buttons": buttons
    }

def handling_messages_with_group(viber_request):
    """Английская буква 'c' не работает, нужна русская. Делаем проверку если вводится группа"""
    message = True
    if viber_request.message.text[-1] == 'c':
        message = str(viber_request.message.text)
        message = ''.join(message[0:6] + 'с')
        html = get_site_html(message, viber_request.message.text, 'search', get_number_this_week())
    else:
        html = get_site_html(message, viber_request.message.text, 'search', get_number_this_week())
    if html.ok:
        soup = BeautifulSoup(html.text, 'html.parser')
        data = soup.find_all('a')
        links = [x.text.strip() for x in data]
        if len(links) > 1:
            buttons = KeyboardMessage(tracking_data='tracking_data', min_api_version=7, keyboard=search_suggestions_buttons(links))
            viber.send_messages(viber_request.sender.id, [
                TextMessage(text="Вот несколько вариантов"), buttons
            ])
            return False
        elif len(links) == 1:
            write_data_in_db(viber_request, links[0])
            return True
        else:
            viber.send_messages(viber_request.sender.id, [
                TextMessage(text="Ничего не найдено, повторите ввод")
            ])
            return False
    elif IndexError:
        return Exception
    else:
        return ConnectionError


def message(viber_request):
    viber.send_messages(viber_request.sender.id, [
        TextMessage(text="Для получения другого расписания просто введите группу или фамилию преподавателя")
    ])


def del_img():
    dir = 'static'
    for f in os.listdir(dir):
        time.sleep(2)
        os.remove(os.path.join(dir, f))


@app.route('/', methods=['POST'])
def incoming():
    print("received request. post data: {0}".format(request.get_data()))
    if not viber.verify_signature(request.get_data(), request.headers.get('X-Viber-Content-Signature')):
        return Response(status=403)

    viber_request = viber.parse_request(request.get_data())

    if isinstance(viber_request, ViberMessageRequest):
        message_timestamp = viber_request.timestamp
        if current_timestamp.count(message_timestamp) != 0:
            return Response(status=200)
        if len(current_timestamp) >= 30:
            del current_timestamp[0]
        current_timestamp.append(message_timestamp)
        try:
            random_str = generate_random_str()
            if viber_request.message.text == 'this_week':
                cur.execute(f"SELECT miuGroup FROM tgdata WHERE tgid = '{viber_request.sender.id}' LIMIT 1")
                data = str(cur.fetchone()[0])
                img = parse_web_site(data, get_number_this_week())
                del_img()
                with open(f"static/{random_str}.jpg", 'wb') as file:
                    file.write(img)
                    viber.send_messages(viber_request.sender.id,
                                        [PictureMessage(
                                            media=f'{ngrok_http}/static/{random_str}.jpg',
                                            text=f"Вот расписание на эту неделю у {data}")])
                message(viber_request)

            elif viber_request.message.text == 'next_week':
                cur.execute(f"SELECT miuGroup FROM tgdata WHERE tgid = '{viber_request.sender.id}' LIMIT 1")
                data = str(cur.fetchone()[0])
                img = parse_web_site(data, get_number_this_week() + 1)
                del_img()
                with open(f"static/{random_str}.jpg", 'wb') as file:
                    file.write(img)
                    viber.send_messages(viber_request.sender.id,
                                        [PictureMessage(
                                            media=f"{ngrok_http}/static/{random_str}.jpg",
                                            text=f"Вот расписание на следующую неделю у {data}")])
                message(viber_request)

            else:
                week = KeyboardMessage(tracking_data='tracking_data', min_api_version=7, keyboard=WEEK_KEYBOARD)
                is_change_week = handling_messages_with_group(viber_request)

                if is_change_week:
                    viber.send_messages(viber_request.sender.id, [
                        TextMessage(text="Выбор недели"), week
                    ])
        except Exception:
            viber.send_messages(viber_request.sender.id, [
                TextMessage(text="Похоже неделя ещё недоступна, повторите ввод или попробуйте позже"),
            ])
    elif isinstance(viber_request, ViberSubscribedRequest):
        viber.send_messages(viber_request.user.id, [
            TextMessage(text="Введите группу или фамилию преподавателя для получения расписания")
        ])
    elif isinstance(viber_request, ViberFailedRequest):
        print("client failed receiving message. failure: {0}".format(viber_request))

    return Response(status=200)


if __name__ == "__main__":
    context = ('server.crt', 'server.key')
    app.run(port=9000)

import requests
import random
import string
import telebot
from telebot import types
import threading
import time
import sqlite3

API = 'https://www.1secmail.com/api/v1/'
domain_list = ["1secmail.com", "1secmail.org", "1secmail.net"]
domain = random.choice(domain_list)

bot_token = 'TOKEN'
bot = telebot.TeleBot(bot_token)

data_lock = threading.Lock()
user_threads = {}
DATABASE = 'user_data.db'

processed_messages = {}


def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT,
            thread_running BOOLEAN
        )
    ''')
    conn.commit()
    conn.close()


def generate_username():
    name = string.ascii_lowercase + string.digits
    username = ''.join(random.choice(name) for i in range(10))
    return username


def check_mail(mail):
    req_link = f'{API}?action=getMessages&login={mail.split("@")[0]}&domain={mail.split("@")[1]}'
    r = requests.get(req_link).json()
    return r


def delete_mail(mail):
    url = 'https://www.1secmail.com/mailbox'
    data = {
        'action': 'deleteMailbox',
        'login': mail.split('@')[0],
        'domain': mail.split('@')[1]
    }
    r = requests.post(url, data=data)
    return r.status_code == 200


def notify_new_mail(user_id, mail):
    while user_id in user_threads and user_threads[user_id]:
        messages = check_mail(mail)
        if messages:
            with data_lock:
                if not user_threads[user_id]:
                    break
            for msg in messages:
                msg_id = msg['id']
                if msg_id not in processed_messages.get(user_id, []):
                    read_msg = f'{API}?action=readMessage&login={mail.split("@")[0]}&domain={mail.split("@")[1]}&id={msg_id}'
                    r = requests.get(read_msg).json()
                    sender = r.get('from')
                    subject = r.get('subject')
                    date = r.get('date')
                    content = r.get('textBody')
                    bot.send_message(user_id,
                                     f'[НОВОЕ СООБЩЕНИЕ]\nОт: {sender}\nКому: {mail}\nТема: {subject}\nДата: {date}\nСодержание: {content}')
                    processed_messages.setdefault(user_id, []).append(msg_id)
            time.sleep(5)
        else:
            time.sleep(5)


def get_user_email(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT email FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def set_user_email(user_id, email):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, email, thread_running)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) 
        DO UPDATE SET email = excluded.email, thread_running = excluded.thread_running
    ''', (user_id, email, True))
    conn.commit()
    conn.close()


def remove_user(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, 'Привет! Используйте /create_mail для создания временного почтового ящика.')


@bot.message_handler(commands=['create_mail'])
def create_mail(message):
    user_id = message.from_user.id
    old_mail = get_user_email(user_id)
    if old_mail:
        bot.send_message(message.chat.id,
                         f'У вас уже есть почтовый адрес: {old_mail}\nУдаляем старый адрес и создаем новый...')
        delete_mail(old_mail)
        with data_lock:
            user_threads[user_id] = False
            if user_id in processed_messages:
                del processed_messages[user_id]

    username = generate_username()
    mail = f'{username}@{domain}'
    set_user_email(user_id, mail)
    bot.send_message(message.chat.id,
                     f'[+] Ваш новый почтовый адрес: {mail}\nВы можете использовать следующие команды:\n/check_mail - проверить почту\n/delete_mail - удалить почту')

    user_threads[user_id] = True
    threading.Thread(target=notify_new_mail, args=(user_id, mail)).start()


@bot.message_handler(commands=['check_mail'])
def handle_check_mail(message):
    user_id = message.from_user.id
    mail = get_user_email(user_id)
    if mail:
        messages = check_mail(mail)
        if not messages:
            bot.send_message(message.chat.id, '[INFO] На почте пока нет новых сообщений.')
        else:
            for msg in messages:
                msg_id = msg['id']
                if msg_id not in processed_messages.get(user_id, []):
                    read_msg = f'{API}?action=readMessage&login={mail.split("@")[0]}&domain={mail.split("@")[1]}&id={msg_id}'
                    r = requests.get(read_msg).json()
                    sender = r.get('from')
                    subject = r.get('subject')
                    date = r.get('date')
                    content = r.get('textBody')
                    bot.send_message(message.chat.id,
                                     f'Sender: {sender}\nTo: {mail}\nSubject: {subject}\nDate: {date}\nContent: {content}')
                    processed_messages.setdefault(user_id, []).append(msg_id)
    else:
        bot.send_message(message.chat.id,
                         'Не удалось найти ваш почтовый адрес. Используйте команду /create_mail для создания почты.')


@bot.message_handler(commands=['delete_mail'])
def handle_delete_mail(message):
    user_id = message.from_user.id
    mail = get_user_email(user_id)
    if mail:
        if delete_mail(mail):
            bot.send_message(message.chat.id, f'[X] Почтовый адрес {mail} - удален!')
            with data_lock:
                remove_user(user_id)
                user_threads[user_id] = False
                if user_id in processed_messages:
                    del processed_messages[user_id]
        else:
            bot.send_message(message.chat.id, f'[!] Не удалось удалить почтовый адрес {mail}')
    else:
        bot.send_message(message.chat.id,
                         'Не удалось найти ваш почтовый адрес. Используйте команду /create_mail для создания почты.')


def main():
    init_db()
    bot.polling(none_stop=True)


if __name__ == '__main__':
    main()

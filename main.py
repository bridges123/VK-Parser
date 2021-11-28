import requests
import json
import re
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InputMediaPhoto, InputMediaVideo
import asyncio
import sqlite3 as sql
from config import VK_DEV_TOKEN, DEV_ID, TELEGRAM_TOKEN


class Choise(StatesGroup):
    tgid = State()
    firstgroup = State()
    addgroup = State()
    pripiska = State()


storage = MemoryStorage()
bot = Bot(TELEGRAM_TOKEN)
dp = Dispatcher(bot, storage=storage)

con = sql.connect('base.db')
cursor = con.cursor()
cursor.execute("""CREATE TABLE IF NOT EXISTS base(
	ownerid INTEGER,
	access BOOLEAN,
	groupid STRING,
	channelid INTEGER,
	activate BOOLEAN,
	pripiska STRING
)""")
con.commit()


def send_request(group):
    url = f"https://api.vk.com/method/wall.get?domain={group}&count=25&access_token={VK_DEV_TOKEN}&v=5.52"
    req = requests.get(url).json()
    posts = req["response"]["items"]
    return posts


def recompile_news(all_posts, group):
    with open(f"groups/{group}_all_posts.json") as file:
        old_posts = json.load(file)
    new_posts = []
    for post in all_posts:
        post_ids = []
        for post2 in old_posts:
            post_ids.append(post2['post_id'])
        if post['post_id'] not in post_ids:
            new_posts.append(post)
    if new_posts == all_posts:
        new_posts = []
    save_posts(all_posts, group)
    return new_posts


def get_attachments(post):
    postid = post['id']
    post = post['attachments']
    post_photos = []
    post_videos = []

    for i in range(len(post)):
        #-----------PHOTOS-----------
        if post[i]['type'] == 'photo':
            one_photos = []
            for pitem in post[i]['photo']:
                if 'photo' in pitem:
                    one_photos.append(post[i]['photo'][pitem])
            max_size = 0
            for photo in one_photos:
                size = photo.split('?')[-1][5::]
                size = size.split('&')[0]
                size = size.split('x')[0]
                try:
                    max_size = max(int(size), max_size)
                except:
                    print('Trouble with sizing photo ' + str(postid))
            if max_size > 0:
                for photo in one_photos:
                    if f'size={str(max_size)}' in photo:
                        post_photos.append(photo)
                        break
        # -----------VIDEOS-----------
        elif post[i]['type'] == 'video':
            video_access_key = post[i]['video']['access_key']
            video_post_id = post[i]['video']['id']
            video_owner_id = post[i]['video']['owner_id']
            video_get_url = f"https://api.vk.com/method/video.get?videos={video_owner_id}_{video_post_id}_{video_access_key}&access_token={VK_DEV_TOKEN}&v=5.52"
            req = requests.get(video_get_url).json()
            video_url = req['response']['items'][0]['player']
            post_videos.append(video_url)
    return post_photos, post_videos


def get_posts(posts):
    all_posts = []
    for post in posts:
        post_id = post['id']
        post_text = post['text']
        try:
            post_text = re.sub('[^\x00-\x7Fа-яА-Я]', '', post_text)
        except Exception as ex:
            print(ex)
            post_text = ''
        post_photos = []
        post_videos = []
        try:
            if 'attachments' in post:
                post_photos, post_videos = get_attachments(post)
        except Exception as ex:
            print('Ooopss...\n' + str(ex))
        this_post = {
            'post_id': post_id,
            'post_text': post_text,
            'post_photos': post_photos,
            'post_videos': post_videos
        }
        all_posts.append(this_post)
    return all_posts


def save_posts(all_posts, group):
    with open(f"groups/{group}_all_posts.json", "w") as file:
        json.dump(all_posts, file, indent=4, ensure_ascii=False)


async def send_posts(newposts, channelid):
    for post in newposts[::-1]:
        posttext = post['post_text']
        postphotos = post['post_photos']
        postvideos = post['post_videos']
        postmedia = []

        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"SELECT pripiska FROM base WHERE channelid == ?", (channelid,))
        pripiska = cursor.fetchone()
        if pripiska is not None:
            pripiska = pripiska[0]
            posttext = pripiska + '\n\n' + posttext
        if len(postphotos) > 0:
            for pp in postphotos:
                postmedia.append(InputMediaPhoto(pp))
            postmedia[0] = InputMediaPhoto(postphotos[0], caption=posttext)

        if len(postvideos) > 0:
            for pp in postvideos:
                postmedia.append(InputMediaVideo(pp))
        if len(postmedia) > 0:
            try:
                await bot.send_media_group(channelid, postmedia)
            except Exception as ex:
                if len(postphotos) > 0:
                    try:
                        postmedia = []
                        for pp in postphotos:
                            postmedia.append(InputMediaPhoto(pp))
                        postmedia[0] = InputMediaPhoto(postphotos[0], caption=posttext)
                        await bot.send_media_group(channelid, postmedia)
                    except Exception as ex:
                        print(ex)
        else:
            await bot.send_message(channelid, posttext)


def first_cycle(group):
    try:
        posts = send_request(group)
    except Exception as ex:
        print(ex)
        return False
    if len(posts) < 1:
        return False
    elif posts[0]['from_id'] == DEV_ID or posts[0]['owner_id'] == DEV_ID:
        return False
    else:
        all_posts = get_posts(posts)
        save_posts(all_posts, group)
        return True


def main_cycle(group):
    posts = send_request(group)
    if len(posts) < 1:
        return False, []
    elif posts[0]['from_id'] == DEV_ID or posts[0]['owner_id'] == DEV_ID:
        return False, []
    else:
        all_posts = get_posts(posts)
        new_posts = recompile_news(all_posts, group) # рекомпиляция постов
        if len(new_posts) > 0:
            print('Новые посты собраны с  https://vk.com/' + group)
        else:
            print('Нет новых постов в  https://vk.com/' + group)
    return True, new_posts


async def send_all_posts():
    while True:
        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"SELECT groupid FROM base")
        groupids = cursor.fetchall()
        for group in groupids:
            group = group[0]
            con = sql.connect('base.db')
            cursor = con.cursor()
            cursor.execute(f"SELECT channelid FROM base WHERE groupid == ?", (group,))
            channelids = []
            for s in cursor.fetchall():
                channelids += s
            result, newposts = main_cycle(group)
            if result:
                if len(newposts) > 0:
                    for channelid in channelids:
                        con = sql.connect('base.db')
                        cursor = con.cursor()
                        cursor.execute(f"SELECT activate FROM base WHERE channelid == ?", (channelid,))
                        for s in cursor.fetchone():
                            act = s
                        if act:
                            await send_posts(newposts, channelid)
            elif group != '':
                try:
                    con = sql.connect('base.db')
                    cursor = con.cursor()
                    cursor.execute(f"SELECT ownerid FROM base WHERE groupid == ?", (group,))
                    ownids = []
                    for s in cursor.fetchall():
                        ownids += s
                    for own in ownids:
                        await bot.send_message(own, "Произошла ошибка...Выключите бота и напишите в поддержку.")
                except Exception as ex:
                    print(ex)

        await asyncio.sleep(60)


@dp.message_handler(commands=['exit'], state='*')
async def exit(message:types.Message, state: FSMContext):
    if message.chat.id == message.from_user.id:
        current_state = await state.get_state()
        if current_state is not None:
            await state.finish()
            await bot.send_message(message.from_user.id, 'Действие успешно отменено.')
        else:
            await bot.send_message(message.from_user.id, 'Нечего отменять...')
    else:
        await bot.send_message(message.chat.id, 'Пожалуйста, настраивайте бота только в его ЛС.')


@dp.message_handler(commands=['mygroups'], state='*')
async def mygroup(message: types.Message, state: FSMContext):
    if message.chat.id == message.from_user.id:
        current_state = await state.get_state()
        if current_state is not None:
            await state.finish()
        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"SELECT groupid FROM base WHERE ownerid == {message.from_user.id}")
        groupids = []
        for s in cursor.fetchall():
            groupids += s
        if len(groupids) > 0 and groupids[0] != '':
            grouplist = "Список ваших групп (макс. 3):\n"
            for i in range(len(groupids)):
                grouplist += f"{str(i+1)} - vk.com/{groupids[i]}\n"
            grouplist += "\nДля удаления группы используйте /delgroup (номер группы в списке).\nНапример: /delgroup 2"
            await bot.send_message(message.from_user.id, grouplist, disable_web_page_preview=True)
        else:
            await bot.send_message(message.from_user.id, 'В данный момент у вас нет добавленных групп. Воспользуйтесь /addgroup для добавления.')
    else:
        await bot.send_message(message.chat.id, 'Пожалуйста, настраивайте бота только в его ЛС.')


@dp.channel_post_handler(state=Choise.tgid)
async def channel(post, state: FSMContext):
    if post.text != '/startbot':
        try:
            answer = int(post.text)
            con = sql.connect('base.db')
            cursor = con.cursor()
            cursor.execute(f"UPDATE base SET ownerid = ? WHERE channelid == {post.chat.id}", (answer,))
            con.commit()
            await bot.send_message(post.chat.id, 'Отлично! Для дальнейшей настройки бота перейдите в его ЛС.')
            await state.finish()
        except:
            await bot.send_message(post.chat.id, "Пожалуйста, введите корректный id Телеграм!")
    else:
        await state.finish()
        await bot.send_message(post.chat.id, 'Ввод id Телеграм отменен.')


@dp.message_handler(state=Choise.firstgroup)
async def first_group_chosen(message: types.Message, state: FSMContext):
    if message.from_user.id == message.chat.id:
        group_name = message.text
        ownerid = message.from_user.id
        if first_cycle(group_name):
            con = sql.connect('base.db')
            cursor = con.cursor()
            cursor.execute(f"UPDATE base SET groupid = ? WHERE ownerid == {ownerid}", (group_name,))
            con.commit()
            await bot.send_message(message.chat.id, "Группа успешно добавлена.")
            await state.finish()
        else:
            await bot.send_message(message.chat.id, "Попробуйте ввести корректный id группы.")
    else:
        await bot.send_message(message.chat.id, 'Пожалуйста, продолжите настройку бота в его ЛС.')


@dp.message_handler(state=Choise.addgroup)
async def group_chosen(message: types.Message, state: FSMContext):
    if message.from_user.id == message.chat.id:
        group_name = message.text
        ownerid = message.from_user.id
        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"SELECT groupid FROM base WHERE ownerid == ?", (ownerid,))
        groups = []
        for s in cursor.fetchall():
            groups += s
        if group_name not in groups:
            if first_cycle(group_name):
                con = sql.connect('base.db')
                cursor = con.cursor()

                # ----------------ПОЛУЧЕНИЕ ДАННЫХ-------------------
                cursor.execute(f"SELECT access FROM base WHERE ownerid == ?", (ownerid,))
                for s in cursor.fetchone():
                    access = s
                cursor.execute(f"SELECT channelid FROM base WHERE ownerid == ?", (ownerid,))
                for s in cursor.fetchone():
                    channelid = s
                cursor.execute(f"SELECT activate FROM base WHERE ownerid == ?", (ownerid,))
                for s in cursor.fetchone():
                    activate = s
                cursor.execute(f"SELECT pripiska FROM base WHERE ownerid == ?", (ownerid,))
                for s in cursor.fetchone():
                    pripiska = s

                # ---------ЗАПИСЬ НОВОЙ ГРУППЫ НОВЫМ ПОЛЕМ-----------
                cursor.execute(f"INSERT INTO base VALUES (?, ?, ?, ?, ?, ?)",
                               (ownerid, access, group_name, channelid, activate, pripiska))
                con.commit()

                await bot.send_message(message.chat.id, "Группа успешно добавлена.")
                await state.finish()
            else:
                await bot.send_message(message.chat.id, "Попробуйте ввести корректный id группы.")
        else:
            await bot.send_message(message.from_user.id, 'Данная группа уже присутствует в списке.\nПроверить свои '
                                                         'группы: /mygroups')
    else:
        await bot.send_message(message.chat.id, 'Пожалуйста, продолжите настройку бота в его ЛС.')


@dp.message_handler(commands=['addgroup'], state='*')
async def addgroup(message: types.Message, state: FSMContext):
    # ЕСТЬ И ГРУППА И ЗАРЕГАН
    if message.chat.id == message.from_user.id:
        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"SELECT groupid FROM base WHERE ownerid == {message.from_user.id}")
        groupids = []
        for s in cursor.fetchall():
            groupids += s
        if len(groupids) == 0 or groupids[0] == '':
            cursor.execute(f"SELECT ownerid FROM base WHERE ownerid == {message.from_user.id}")
            owner = cursor.fetchone()
            if owner is not None:
                if len(groupids) < 3:
                    await bot.send_message(message.chat.id, "Введите id группы, которую хотите добавить:")
                    await Choise.firstgroup.set()
                else:
                    await bot.send_message(message.chat.id, "У вас закончился лимит добавления групп. (макс. 3)")
            else:
                await bot.send_message(message.from_user.id, 'Воспользуйтесь /startbot для первоначальной настройки бота.')
        else:
            if len(groupids) < 3:
                await bot.send_message(message.chat.id, "Введите id группы, которую хотите добавить:")
                await Choise.addgroup.set()
            else:
                await bot.send_message(message.chat.id, "У вас закончился лимит добавления групп. (макс. 3)")
    else:
        await bot.send_message(message.chat.id, 'Пожалуйста, настраивайте бота только в его ЛС.')


@dp.message_handler(commands=['delgroup'], state='*')
async def delgroup(message: types.Message, state: FSMContext):
    if message.chat.id == message.from_user.id:
        txt = message.text.split()
        if len(txt) == 1:
            await bot.send_message(message.from_user.id, 'Укажите номер группы, который хотите удалить.\nНапример: '
                                                         '/delgroup 2\nНомер группы можно узнать с помощью /mygroups')
        elif len(txt) == 2:
            num = txt[-1]
            if len(num) == 1:
                if ord(num) >= 49 and ord(num) <= 57:
                    num = int(num)
                    con = sql.connect('base.db')
                    cursor = con.cursor()
                    cursor.execute(f"SELECT groupid FROM base WHERE ownerid == {message.from_user.id}")
                    grouplist = []
                    for s in cursor.fetchall():
                        grouplist += s
                    if len(grouplist) > 0 and grouplist[0] != '':
                        if num <= len(grouplist):
                            if len(grouplist) > 1:
                                con = sql.connect('base.db')
                                cursor = con.cursor()
                                cursor.execute(f"DELETE FROM base WHERE ownerid == ? AND groupid == ?", (message.from_user.id, grouplist[num-1]))
                                con.commit()

                                con = sql.connect('base.db')
                                cursor = con.cursor()
                                cursor.execute(f"SELECT groupid FROM base WHERE ownerid == {message.from_user.id}")
                                groupids = []
                                for s in cursor.fetchall():
                                    groupids += s
                                grouplist = "Список ваших групп (макс. 3):\n"
                                for i in range(len(groupids)):
                                    grouplist += f"{str(i + 1)} - vk.com/{groupids[i]}\n"
                                await bot.send_message(message.from_user.id, 'Группа успешно удалена из списка.\n\n' +
                                                       grouplist, disable_web_page_preview=True)
                            elif len(grouplist) == 1:
                                con = sql.connect('base.db')
                                cursor = con.cursor()
                                cursor.execute(f"UPDATE base SET groupid = ? WHERE ownerid == {message.from_user.id}", ('',))
                                con.commit()
                                grouplist = 'В данный момент у вас нет добавленных групп. Воспользуйтесь /addgroup ' \
                                            'для добавления.'
                                await bot.send_message(message.from_user.id,'Группа успешно удалена из списка.\n\n' +
                                                       grouplist, disable_web_page_preview=True)
                            else:
                                print('Ошибка ' + message.from_user.id)
                        else:
                            await bot.send_message(message.from_user.id, 'Введите корректный номер группы.')
                    else:
                        await bot.send_message(message.from_user.id, 'В данный момент у вас нет добавленных групп. Воспользуйтесь /addgroup для добавления.')
                else:
                    await bot.send_message(message.from_user.id, 'Введите корректный номер группы.')
            else:
                await bot.send_message(message.from_user.id, 'Введите корректный номер группы.')
    else:
        await bot.send_message(message.chat.id, 'Пожалуйста, настраивайте бота только в его ЛС.')


@dp.message_handler(state=Choise.pripiska)
async def pripiska_chosen(message: types.Message, state: FSMContext):
    answer = message.text
    if answer != '/pripiska' and answer != 'none':
        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"UPDATE base SET pripiska = ? WHERE ownerid == {message.from_user.id}", (message.text,))
        con.commit()
        await bot.send_message(message.from_user.id, 'Приписка установлена успешно.')
        await state.finish()
    elif answer.lower() == 'none':
        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"UPDATE base SET pripiska = ? WHERE ownerid == {message.from_user.id}", ('',))
        con.commit()
        await bot.send_message(message.from_user.id, 'Приписка успешно удалена.')
        await state.finish()
    elif answer == '/pripiska':
        await bot.send_message(message.from_user.id, 'Для отмены действия введите: /exit\n\nВведите желаемую приписку:')


@dp.message_handler(commands=['pripiska'], state='*')
async def pripison(message):
    if message.chat.id == message.from_user.id:
        con = sql.connect('base.db')
        cursor = con.cursor()
        cursor.execute(f"SELECT pripiska FROM base WHERE ownerid == {message.from_user.id}")
        for s in cursor.fetchone():
            ss = s
        if ss != '':
            await bot.send_message(message.chat.id, f'В данный момент ваша приписка:\n<b>{ss}</b>\n\nДля удаления приписки введите <b>None</b>\nВведите желаемую приписку:', parse_mode=types.ParseMode.HTML)
            await Choise.pripiska.set()
        else:
            await bot.send_message(message.chat.id, f'В данный момент у вас отсутствует приписка.\nВведите желаемую приписку:', parse_mode=types.ParseMode.HTML)
            await Choise.pripiska.set()
    else:
        await bot.send_message(message.chat.id, 'Пожалуйста, настраивайте бота только в его ЛС.')


@dp.channel_post_handler(state='*')
async def channel(post, state: FSMContext):
    if post.text != '/startbot':
        await bot.send_message(post.chat.id, "Я вас не понимаю! Используйте /startbot")
    else:
        current_state = await state.get_state()
        if current_state is None:
            con = sql.connect('base.db')
            cursor = con.cursor()
            cursor.execute(f"SELECT ownerid FROM base WHERE channelid == {post.chat.id}")
            ownerid = cursor.fetchone()
            if ownerid is not None:
                if ownerid[0] is not None:
                    await bot.send_message(post.chat.id, 'Пожалуйста, перейдите в ЛС бота для его настройки.')
                else:
                    # ЗАРЕГАН НО БЕЗ OWNER ID
                    await bot.send_message(post.chat.id,
                                           "Пожалуйста, введите свой id Телеграм ниже:\n(узнать свой id можно, написав боту @userinfobot)\nЧтобы отменить ввод id Телеграм введите /startbot снова.")
                    await Choise.tgid.set()
            else:
                # НЕ ЗАРЕГАН ВООБЩЕ
                await bot.send_message(post.chat.id,
                                       "Пожалуйста, введите свой id Телеграм ниже:\n(узнать свой id можно, написав боту @userinfobot)\nЧтобы отменить ввод id Телеграм введите /startbot снова.")
                con = sql.connect('base.db')
                cursor = con.cursor()
                cursor.execute(f"INSERT INTO base VALUES (?, ?, ?, ?, ?, ?)",
                               (None, True, "", post.chat.id, False, ""))
                con.commit()
                await Choise.tgid.set()


@dp.message_handler(commands=['startbot'], state='*')
async def start(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == 'Choise:tgid':
        await bot.send_message(message.chat.id, 'Пожалуйста, вернитесь в канал для донастройки бота.')
    elif current_state is not None:
        await state.finish()
    con = sql.connect('base.db')
    cursor = con.cursor()
    cursor.execute(f"SELECT ownerid FROM base WHERE ownerid == {message.from_user.id}")
    ownerid = cursor.fetchone()
    if ownerid is not None:
        cursor.execute(f"SELECT groupid FROM base WHERE ownerid == {message.from_user.id}")
        groupids = []
        for s in cursor.fetchall():
            groupids += s
        if len(groupids) == 0 or groupids[0] == '':
            # ЗАРЕГАН НО БЕЗ ГРУППЫ
            if message.chat.id == message.from_user.id:
                await bot.send_message(message.chat.id, "Введите id группы, которую хотите добавить:")
                await Choise.firstgroup.set()
            else:
                await bot.send_message(message.chat.id, 'Пожалуйста, настраивайте бота только в его ЛС.')
        else:
            # ЕСТЬ И ГРУППА И ЗАРЕГАН
            if message.chat.id == message.from_user.id:
                con = sql.connect('base.db')
                cursor = con.cursor()
                cursor.execute(f"SELECT activate FROM base WHERE ownerid == {message.from_user.id}")
                for s in cursor.fetchone():
                    act = s
                if act:
                    cursor.execute(f"UPDATE base SET activate = ? WHERE ownerid == {message.from_user.id}",
                                   (False,))
                    con.commit()
                    await bot.send_message(message.from_user.id, "Бот деактивирован.")
                else:
                    cursor.execute(f"UPDATE base SET activate = ? WHERE ownerid == {message.from_user.id}",
                                   (True,))
                    con.commit()
                    await bot.send_message(message.from_user.id, "Бот активирован.")
            else:
                await bot.send_message(message.chat.id, 'Активируйте бота в его ЛС.')
    else:
        # НЕ ЗАРЕГАН ВООБЩЕ
        await bot.send_message(message.chat.id, "Пожалуйста, проведите первоначальную активацию в Телеграм канале.")


@dp.message_handler(commands=['help', 'start'], state='*')
async def help(message: types.Message, state: FSMContext):
    if message.from_user.id == message.chat.id:
        await bot.send_message(message.from_user.id, 'Добро пожаловать в <b>VK Post Bot</b>. Данный бот будет '
                               'отправлять все новые посты с добавленных вами групп ВК прямо в '
                               'Телеграм канал. Список доступных вам комманд:\n\n'
                               '/startbot - активация Бота\n'
                               '/exit - отмена текущего действия\n'
                               '/mygroups - добавленные группы\n'
                               '/addgroup - добавить новую группу\n'
                               '/delgroup - удалить группу\n'
                               '/pripiska - изменить приписку (пользовательский текст в начале каждого поста)',
                               parse_mode=types.ParseMode.HTML)
    else:
        await bot.send_message(message.from_user.id, 'Пожалуйста, настраивайте бота только в его ЛС.')


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(send_all_posts())
    executor.start_polling(dp, skip_updates=True)

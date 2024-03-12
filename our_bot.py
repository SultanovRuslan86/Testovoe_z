import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import ParseMode
from aiogram.utils import executor

from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import datetime
import requests

from dotenv import load_dotenv
import os

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_URI = os.getenv("DB_URI")

Base = declarative_base()


class States(StatesGroup):
    waiting_info = State()


class QueryHistory(Base):
    __tablename__ = 'query_history'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    time_of_query = Column(DateTime, default=datetime.datetime.utcnow)
    product_id = Column(String)


engine = create_engine(DB_URI)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())



@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add('Получить информацию по товару', 'Остановить уведомления', 'Получить информацию из БД')
    await message.answer('Выберите действие', reply_markup=keyboard)


@dp.message_handler(lambda message: message.text == 'Получить информацию по товару')
async def get_product_info(message: types.Message):
    await message.answer('Введите артикул товара с Wildberries:')
    await States.waiting_info.set()


@dp.message_handler(state=States.waiting_info)
async def process_waiting_info(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['product_id'] = message.text
    await state.finish()
    await get_product_details(message)


async def get_product_details(message: types.Message):
    product_id = message.text
    url = f"https://card.wb.ru/cards/v1/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={product_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        product_data = response.json()['data']['products'][0]
        print("Полученная информация о товаре:", product_data)

        product_info = {
            'product_id': product_id,
            'info': f"Название: {product_data['name']}\n"
                    f"Артикул: {product_id}\n"
                    f"Цена: {product_data['salePriceU']}\n"
                    f"Рейтинг: {product_data['reviewRating']}\n"
                    f"Количество товара на складах: {product_data['sizes'][0]['stocks'][0]['qty']}"
        }

        await message.answer(product_info['info'], parse_mode=ParseMode.HTML)
        await message.answer("Желаете подписаться на уведомления?", reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(text="Подписаться", callback_data=f"subscribe_{product_id}")
        ))

        chat_id = message.chat.id
        asyncio.create_task(notify_subscription(product_info, chat_id))
        await save_query_history(message.from_user.id, product_id)
    except requests.exceptions.HTTPError as err:
        print("HTTP ошибка:", err)
        print("Текст ответа:", response.text)
        await message.answer("Произошла ошибка при получении информации о товаре.")
    except Exception as e:
        print("Произошла ошибка при получении информации о товаре:", e)
        await message.answer("Произошла ошибка при получении информации о товаре.")


@dp.callback_query_handler(lambda c: c.data.startswith('subscribe_'))
async def subscribe(callback_query: types.CallbackQuery):
    await subscribe_to_notifications(callback_query)


subscriptions = {}


async def notify_subscription(product_info: dict, chat_id: int):
    while True:
        product_id = product_info['product_id']
        if chat_id not in subscriptions or product_id not in subscriptions[chat_id]:
            return

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Остановить уведомления", callback_data="stop_subscription"))

        message_text = (f"Уведомление: новая информация о товаре\n"
                        f"Название: {product_info['name']}\n"
                        f"Артикул: {product_info['product_id']}\n"
                        f"Цена: {product_info['price']}\n"
                        f"Рейтинг: {product_info['rating']}\n"
                        f"Количество товара на складах: {product_info['quantity']}\n")

        await bot.send_message(chat_id, message_text, reply_markup=keyboard)

        await asyncio.sleep(15)


@dp.message_handler(lambda message: message.text == 'Получить информацию по товару')
async def get_product_info(message: types.Message):
    await message.answer('Введите артикул товара с Wildberries:')
    await States.waiting_info.set()


@dp.message_handler(state=States.waiting_info)
async def process_waiting_info(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['product_id'] = message.text
    await state.finish()


async def subscribe_to_notifications(callback_query: types.CallbackQuery):
    await callback_query.answer()
    product_id = callback_query.data.split('_')[1]
    chat_id = callback_query.from_user.id

    product_info = await get_product_details_info(product_id)

    if chat_id not in subscriptions:
        subscriptions[chat_id] = set()
    subscriptions[chat_id].add(product_info['product_id'])

    asyncio.create_task(notify_subscription(product_info, chat_id))


async def get_product_details_info(product_id: str):
    url = f"https://card.wb.ru/cards/v1/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={product_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        product_data = response.json()
        product_info = {
            'product_id': product_id,
            'name': product_data['data']['products'][0]['name'],
            'price': product_data['data']['products'][0]['salePriceU'],
            'rating': product_data['data']['products'][0]['reviewRating'],
            'quantity': product_data['data']['products'][0]['sizes'][0]['stocks'][0]['qty']
        }
        return product_info
    except requests.exceptions.HTTPError as err:
        print("HTTP ошибка:", err)
        print("Текст ответа:", response.text)
        raise RuntimeError("Произошла ошибка при получении информации о товаре.")
    except Exception as e:
        print("Произошла ошибка при получении информации о товаре:", e)
        raise RuntimeError("Произошла ошибка при получении информации о товаре.")


@dp.callback_query_handler(lambda c: c.data == 'stop_subscription')
async def stop_subscription(callback_query: types.CallbackQuery):
    chat_id = callback_query.from_user.id
    if chat_id in subscriptions:
        subscriptions.pop(chat_id)
    await callback_query.answer("Уведомления остановлены.")


@dp.message_handler(lambda message: message.text == "Получить информацию из БД")
async def get_info_from_db(message: types.Message):
    session = Session()
    query_history = session.query(QueryHistory).order_by(QueryHistory.time_of_query.desc()).limit(5).all()
    session.close()
    if query_history:
        result = "Последние запросы из БД:\n"
        for query in query_history:
            result += f"Артикул товара: {query.product_id}, Время запроса: {query.time_of_query}\n"
        await message.answer(result)
    else:
        await message.answer("В БД пока нет записей.")


async def save_query_history(user_id: int, product_id: str):
    session = Session()
    query = QueryHistory(user_id=user_id, product_id=product_id)
    session.add(query)
    session.commit()
    session.close()

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
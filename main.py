import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, CallbackQueryHandler, ConversationHandler, CallbackContext
)
from PIL import Image
import cv2
import numpy as np
import sys
import io
import os
from pprint import pformat
from config import BOT_TOKEN, MASTER_CHAT_ID, BASE_RATE_PER_CM2, BASE_RATE_PER_CM, MINIMAL_PRICE

# Установка UTF-8 как стандартной кодировки для вывода
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,  # Было INFO, теперь DEBUG
    handlers=[
        logging.FileHandler("tattoo_bot_debug.log"),  # Запись в файл
        logging.StreamHandler()  # Вывод в консоль
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Дополнительная страховка

# Состояния диалога
(
    SELECT_ACTION, GET_IMAGE, GET_HEIGHT,
    IMAGE_ANALYSIS_DONE,
    MANUAL_QUESTION_TYPE, MANUAL_QUESTION_LOCATION,
    MANUAL_QUESTION_SIZE, MANUAL_QUESTION_DETAIL,
    IMAGE_QUESTION_LOCATION
) = range(9)


# Вопросы для ручного расчета
manual_questions = [
    {
        "key": "type",
        "text": "Это новая татуировка или перекрытие старой?",
        "options": [
            ("Новая татуировка", 1.0),
            ("Перекрытие", 1.5)
        ],
        "image": "q1.jpg"
    },
    {
        "key": "location",
        "text": "На каком участке тела будет татуировка?",
        "options": [
            ("Шея", 1.5),
            ("Грудь", 1.0),
            ("Плечо", 1.0),
            ("Предплечье", 1.0),
            ("Ребра", 1.5),
            ("Спина", 1.0),
            ("Бедро", 1.0),
            ("Голень", 1.0)
        ],
        "image": "q2.jpg"
    },
    {
        "key": "size",
        "text": "Какого размера будет татуировка?",
        "options": [
            ("Маленькая (как ладошка или меньше)", 1),
            ("Средняя (хорошо смотрится на а4, с запасом)", 1.5),
            ("Большая (чуть больше а4)", 2.0),
            ("Очень большой проект (рукав, бедро и тд)", "special")
        ],
        "image": "q3.jpg"
    },
    {
        "key": "detail",
        "text": "Насколько высокая детализация?",
        "options": [
            ("Низкая", 0.5),
            ("Средняя", 1.0),
            ("Высокая", 2.0)
        ],
        "image": "q4.jpg"
    }
]

async def start(update: Update, context: CallbackContext) -> int:
    """быстрое приключение на пять минут начинается здесь"""
    keyboard = [
        [InlineKeyboardButton("Загрузить картинку", callback_data='image')],
        [InlineKeyboardButton("Пройти тестик", callback_data='manual')]
    ]
    await update.message.reply_text(
        "Привет! Я помогу рассчитать стоимость тату. Есть два варианта.\n"
        "Пройти тестик - тыкаем кнопки, выбираем параметры и считаем по ним.\n"
        "Загрузить изображение того, что примерно хочется и все (почти волшебно) посчитается.\n"
        "Сделай выбор:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_ACTION

async def select_action(update: Update, context: CallbackContext) -> int:
    """поворот не туда"""
    query = update.callback_query
    await query.answer()

    if query.data == 'image':
        await query.edit_message_text(text="Тут нужно отправить картинку того, что примерно хочется\n"
                                           "Лучше всего - изображение на белом фоне\n"
                                           "\n"
                                           "Можно найти что-нибудь в пинтересте, на что мы будем ориентироваться сейчас. Посчитаем по нему, а потом Кварк создаст подобный эскиз!")
        return GET_IMAGE
    else:
        context.user_data['calculation_type'] = 'manual'
        context.user_data['answers'] = {}
        context.user_data['current_question'] = 0
        await ask_manual_question(update, context)
        return MANUAL_QUESTION_TYPE

async def ask_manual_question(update: Update, context: CallbackContext):
    """Задаем вопрос с вариантами ответа для ручного расчета"""
    question_index = context.user_data['current_question']
    question = manual_questions[question_index]

    # Создаем кнопки с индексами вариантов (0, 1, 2...)
    keyboard = [
        [InlineKeyboardButton(text, callback_data=f"ans_{question_index}_{idx}")]
        for idx, (text, _) in enumerate(question["options"])  # Используем индекс вместо значения
    ]

    try:
        # Пытаемся отправить вопрос с изображением
        with open(f"images/{question['image']}", "rb") as photo:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo,
                caption=question["text"],
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except FileNotFoundError:
        # Если изображение не найдено, отправляем только текст
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=question["text"],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )



async def handle_manual_answer(update: Update, context: CallbackContext) -> int:
    """Обработка ответа на вопрос ручного расчета"""
    query = update.callback_query
    await query.answer()

    try:
        # Разбираем callback_data: "ans_<question_index>_<option_index>"
        _, question_index_str, option_index_str = query.data.split('_')
        question_index = int(question_index_str)
        option_index = int(option_index_str)

        # Получаем текущий вопрос и выбранный вариант
        current_question = manual_questions[question_index]
        option_text, option_value = current_question["options"][option_index]

        # Сохраняем ответ
        context.user_data['answers'][current_question["key"]] = {
            "value": option_value,
            "label": option_text
        }

        logger.debug(f"Сохранен ответ: {current_question['key']} = {option_text} ({option_value})")

        # Определяем следующий вопрос или завершаем расчет
        next_question_index = question_index + 1
        if next_question_index < len(manual_questions):
            context.user_data['current_question'] = next_question_index
            await ask_manual_question(update, context)

            # Возвращаем соответствующее состояние
            states = {
                0: MANUAL_QUESTION_TYPE,
                1: MANUAL_QUESTION_LOCATION,
                2: MANUAL_QUESTION_SIZE,
                3: MANUAL_QUESTION_DETAIL
            }
            return states[next_question_index]
        else:
            return await finish_manual_calculation(update, context)

    except Exception as e:
        logger.error(f"Ошибка обработки ответа: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка. Пожалуйста, начните расчет заново.")
        return ConversationHandler.END


async def finish_manual_calculation(update: Update, context: CallbackContext) -> int:
    """конец порнографии"""
    query = update.callback_query
    await query.answer()

    answers = context.user_data['answers']

    # Проверяем, не выбран ли "большой проект"
    if answers['size']['value'] == "special":
        message = (
            "Судя по всему, у тебя довольно большой проект, стоимость которого сложно посчитать без оценки мастера.\n"
            "Обычно это значит, что такую работу можно сделать не менее чем за три сеанса - 15.000 за каждый.\n"
            "Для уточнений пожалуйста вызывайте Кварка."
        )
        keyboard = [
            [InlineKeyboardButton("Связаться с мастером", callback_data="contact_yes")],
            [InlineKeyboardButton("Отмена", callback_data="contact_no")]
        ]
    else:
        # Рассчитываем стоимость по формуле
        price = MINIMAL_PRICE
        for key in ['type', 'location', 'size', 'detail']:
            price *= answers[key]['value']
        price = int(price)

        message = (
            f"  Твои ответы:\n"
            f"▸ Тип: {answers['type']['label']}\n"
            f"▸ Местоположение: {answers['location']['label']}\n"
            f"▸ Размер: {answers['size']['label']}\n"
            f"▸ Детализация: {answers['detail']['label']}\n\n"
            f"▸ Ориентировочная стоимость: {price} ₽\n"
            f"В случае, если стоимость вышла больше 30.000, скорее всего эта работа делается не за один сеанс.\n"
            f"Если она делается не за один сеанс, то оплачивается не разово, а каждый сеанс отдельно - по 15000.\n\n"
            f"  Связаться с мастером?"
        )
        keyboard = [
            [InlineKeyboardButton("Да", callback_data="contact_yes")],
            [InlineKeyboardButton("Нет", callback_data="contact_no")]
        ]

    try:
        await query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        # logger.error(f"Ошибка при редактировании сообщения: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    return IMAGE_ANALYSIS_DONE

async def get_height(update: Update, context: CallbackContext) -> int:
    """Обработка введенной высоты"""
    try:
        height_cm = float(update.message.text)
        if height_cm <= 0:
            raise ValueError("Высота должна быть больше 0.")
        context.user_data['height_cm'] = height_cm
        await ask_location_question(update, context)
        return IMAGE_QUESTION_LOCATION  # Используем новое состояние
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи число больше 0 (например, 10):")
        return GET_HEIGHT


async def ask_location_question(update: Update, context: CallbackContext):
    """Задаем вопрос о местоположении тату"""
    location_question = next(q for q in manual_questions if q["key"] == "location")

    keyboard = [
        [InlineKeyboardButton(text, callback_data=f"img_loc_{idx}")]
        for idx, (text, _) in enumerate(location_question["options"])
    ]

    try:
        with open(f"images/{location_question['image']}", "rb") as photo:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo,
                caption=location_question["text"],
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except FileNotFoundError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=location_question["text"],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def handle_location_answer(update: Update, context: CallbackContext) -> int:
    """Обработка выбора местоположения для расчета по изображению"""
    query = update.callback_query
    await query.answer()

    try:
        option_index = int(query.data.split('_')[-1])
        location_question = next(q for q in manual_questions if q["key"] == "location")
        option_text, option_value = location_question["options"][option_index]

        context.user_data['location'] = {
            "value": option_value,
            "label": option_text
        }

        return await analyze_image(update, context)
    except Exception as e:
        logger.error(f"Ошибка обработки местоположения: {e}")
        await query.edit_message_text("Произошла ошибка. Пожалуйста, начни заново.")
        return ConversationHandler.END


async def analyze_image(update: Update, context: CallbackContext) -> int:
    """Анализ изображения и расчет стоимости с учетом местоположения"""
    try:
        # Получаем chat_id из callback_query или message
        chat_id = update.effective_chat.id
        query = update.callback_query

        # Загрузка изображения из user_data
        image_data = context.user_data['image']
        image_pil = Image.open(image_data)
        height_cm = context.user_data['height_cm']
        location_factor = context.user_data['location']['value']

        # Конвертация прозрачного фона в белый
        if image_pil.mode == 'RGBA':
            white_bg = Image.new('RGB', image_pil.size, (255, 255, 255))
            white_bg.paste(image_pil, mask=image_pil.split()[3])
            image_pil = white_bg

        image_np = np.array(image_pil)

        # Сохранение оригинального изображения для отладки
        cv2.imwrite("debug_original.png", cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR))

        # Предобработка изображения
        gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)

        # Бинаризация
        _, th1 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        th2 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY_INV, 21, 10)
        binary = cv2.bitwise_or(th1, th2)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        cv2.imwrite("debug_binary.png", binary)

        # Нахождение контуров
        contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            raise ValueError("Не найдено контуров")

        # Расчет параметров
        px_per_cm = image_np.shape[0] / height_cm
        areas = improved_calculate_areas(binary, contours, px_per_cm)

        # Определение типа тату
        tattoo_type = "outline"
        if areas['filled'] > 0:
            fill_ratio = areas['filled'] / (areas['contour'] + 1e-5)
            roi_mask = np.zeros_like(gray)
            cv2.drawContours(roi_mask, contours, -1, 255, cv2.FILLED)
            texture_std = cv2.meanStdDev(gray, mask=roi_mask)[1][0][0]

            if fill_ratio > 0.7 and texture_std < 30:
                tattoo_type = "filled"
            elif fill_ratio > 0.2 or texture_std > 30:
                tattoo_type = "mixed"

        contours_count = len(contours)

        # Сохранение данных
        context.user_data.update({
            'image_area': areas['filled'],
            'contour_area': areas['contour'],
            'perimeter_cm': areas['perimeter'],
            'contours_count': contours_count,
            'tattoo_type': tattoo_type
        })

        # Расчет цены с учетом местоположения
        price = calculate_price(
            filled_area=areas['filled'],
            contour_area=areas['contour'],
            perimeter=areas['perimeter'],
            contours_count=contours_count,
            tattoo_type=tattoo_type,
            location_factor=location_factor
        )
        context.user_data['price'] = price

        # Формирование отчета
        type_names = {
            'outline': 'Контурная',
            'filled': 'Заполненная',
            'mixed': 'Смешанная'
        }

        complexity_level = (
            "Низкая" if contours_count < 15 else
            "Средняя" if contours_count < 1000 else
            "Высокая"
        )

        report_message = (
            f"Результаты анализа:\n"
            f"▸ Тип: {type_names.get(tattoo_type, 'Неизвестный')}\n"
            f"▸ Местоположение: {context.user_data['location']['label']}\n"
            f"▸ Площадь: {areas['filled']:.1f} см²\n"
            f"▸ Периметр: {areas['perimeter']:.1f} см\n"
            f"▸ Контуров: {contours_count} ({complexity_level} сложность)\n"
            f"  Приблизительная стоимость: {price} ₽\n\n"
            f"В случае, если стоимость вышла больше 30.000, скорее всего эта работа делается не за один сеанс.\n"
            f"Если она делается не за один сеанс, то оплачивается не разово, а каждый сеанс отдельно - по 15000.\n\n"
            f"Связаться с мастером?"
        )

        keyboard = [
            [InlineKeyboardButton("Да", callback_data="contact_yes")],
            [InlineKeyboardButton("Нет", callback_data="contact_no")]
        ]

        # Отправляем обработанное изображение и результаты
        await send_processed_image(context.bot, chat_id, image_np, binary, contours, tattoo_type)
        await context.bot.send_message(
            chat_id=chat_id,
            text=report_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        return IMAGE_ANALYSIS_DONE

    except Exception as e:
        logger.error(f"Ошибка анализа изображения: {str(e)}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Произошла ошибка при анализе. Попробуй другое изображение."
        )
        return SELECT_ACTION

# async def get_height1(update: Update, context: CallbackContext) -> int:
#     """Обработка введенной высоты и анализ изображения"""
#     try:
#         height_cm = float(update.message.text)
#         if height_cm <= 0:
#             raise ValueError("Высота должна быть больше 0.")
#     except ValueError:
#         await update.message.reply_text("Пожалуйста, введите число больше 0 (например, 10):")
#         return GET_HEIGHT
#
#     try:
#         # Загрузка и предобработка изображения
#         image_pil = Image.open(context.user_data['image'])
#
#         # Конвертация прозрачного фона в белый
#         if image_pil.mode == 'RGBA':
#             white_bg = Image.new('RGB', image_pil.size, (255, 255, 255))
#             white_bg.paste(image_pil, mask=image_pil.split()[3])
#             image_pil = white_bg
#
#         image_np = np.array(image_pil)
#
#         # Сохранение оригинального изображения для отладки
#         cv2.imwrite("debug_original.png", cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR))
#         # logger.debug("Оригинал сохранен в debug_original.png")
#
#         # Улучшенная предобработка
#         gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
#         gray = cv2.GaussianBlur(gray, (7, 7), 0)
#
#         # Комбинированная бинаризация
#         _, th1 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
#         th2 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#                                     cv2.THRESH_BINARY_INV, 21, 10)
#         binary = cv2.bitwise_or(th1, th2)
#         binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
#
#         # Сохранение бинаризованного изображения
#         cv2.imwrite("debug_binary.png", binary)
#         # logger.debug(f"Бинаризация сохранена. Уникальные значения: {np.unique(binary)}")
#
#         # Нахождение контуров
#         contours, hierarchy = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
#         if not contours:
#             raise ValueError("Не найдено контуров")
#
#         # Расчет параметров
#         px_per_cm = image_np.shape[0] / height_cm
#         areas = improved_calculate_areas(binary, contours, px_per_cm)
#
#         # Улучшенное определение типа тату
#         tattoo_type = "outline"  # По умолчанию
#
#         if areas['filled'] > 0:
#             fill_ratio = areas['filled'] / (areas['contour'] + 1e-5)
#
#             # Анализ текстуры внутри контура
#             roi_mask = np.zeros_like(gray)
#             cv2.drawContours(roi_mask, contours, -1, 255, cv2.FILLED)
#             texture_std = cv2.meanStdDev(gray, mask=roi_mask)[1][0][0]
#
#             if fill_ratio > 0.7 and texture_std < 30:
#                 tattoo_type = "filled"
#             elif fill_ratio > 0.2 or texture_std > 30:
#                 tattoo_type = "mixed"
#
#         # logger.debug(
#         #     "Детали расчета:\n"
#         #     f"- Fill/Contour ratio: {fill_ratio:.2f}\n"
#         #     f"- Texture std: {texture_std:.2f}\n"
#         #     f"- Filled: {areas['filled']:.2f} см²\n"
#         #     f"- Contour: {areas['contour']:.2f} см²\n"
#         #     f"- Perimeter: {areas['perimeter']:.2f} см\n"
#         #     f"- Detected type: {tattoo_type}"
#         # )
#
#         contours_count = len(contours)
#
#         # Сохранение данных
#         context.user_data.update({
#             'image_area': areas['filled'],
#             'contour_area': areas['contour'],
#             'perimeter_cm': areas['perimeter'],
#             'contours_count': contours_count,
#             'tattoo_type': tattoo_type
#         })
#
#         context.user_data['price'] = calculate_price(
#             areas['filled'],
#             areas['contour'],
#             areas['perimeter'],
#             contours_count,
#             tattoo_type  # Передаем тип как именованный аргумент
#         )
#
#         # Формирование отчета
#         type_names = {
#             'outline': 'Контурная',
#             'filled': 'Заполненная',
#             'mixed': 'Смешанная'
#         }
#
#         complexity_level = (
#             "Низкая" if contours_count < 15 else
#             "Средняя" if contours_count < 1000 else
#             "Высокая"
#         )
#
#         report_message = (
#             f"**Результаты анализа:**\n"
#             f"▸ Тип: {type_names.get(tattoo_type, 'Неизвестный')}\n"
#             f"▸ Площадь: {areas['filled']:.1f} см²\n"
#             f"▸ Периметр: {areas['perimeter']:.1f} см\n"
#             f"▸ Контуров: {contours_count} ({complexity_level} сложность)\n"
#             f"**Приблизительная стоимость:** {context.user_data['price']} ₽"
#             f"\n\nСвязаться с мастером?"
#         )
#
#         keyboard = [
#             [InlineKeyboardButton("Да", callback_data="contact_yes")],
#             [InlineKeyboardButton("Нет", callback_data="contact_no")]
#         ]
#
#         await send_processed_image(update, image_np, binary, contours, tattoo_type)
#         await update.message.reply_text(
#             report_message,
#             reply_markup=InlineKeyboardMarkup(keyboard),
#             parse_mode="Markdown"
#         )
#         return IMAGE_ANALYSIS_DONE
#
#     except Exception as e:
#         # logger.error(f"Ошибка: {str(e)}", exc_info=True)
#         await update.message.reply_text("Произошла ошибка при анализе. Попробуйте другое изображение.")
#         return SELECT_ACTION


def determine_tattoo_type(areas):
    try:
        if areas['filled'] < 1.0:  # Совсем маленькие области
            return 'outline'

        fill_ratio = areas['filled'] / (areas['contour'] + 1e-5)

        if fill_ratio > 0.7:  # Больше заполнения
            return 'filled'
        elif fill_ratio > 0.3:  # Среднее заполнение
            return 'mixed'
        else:  # Чистые контуры
            return 'outline'
    except Exception as e:
        # logger.error(f"Ошибка определения типа: {e}")
        return 'outline'  # Значение по умолчанию
async def get_image(update: Update, context: CallbackContext) -> int:
    """Обработка загруженного изображения"""
    try:
        # Получаем фото максимального качества
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()

        # Сохраняем в user_data для использования в get_height
        image_data = io.BytesIO()
        await photo_file.download_to_memory(image_data)
        image_data.seek(0)
        context.user_data['image'] = image_data

        await update.message.reply_text(
            "Изображение получено! Теперь укажи желаемую высоту тату в см (например, 10):"
        )
        return GET_HEIGHT

    except Exception as e:
        # logger.error(f"Ошибка загрузки фото: {e}")
        await update.message.reply_text(
            "Не удалось обработать изображение. Пожалуйста, попробуй ещё раз или выбери другой файл."
        )
        return SELECT_ACTION

async def handle_contact_decision(update: Update, context: CallbackContext) -> int:
    """земля вызывает"""
    query = update.callback_query
    await query.answer()

    if query.data == "contact_yes":
        user = query.from_user
        answers = context.user_data.get('answers', {})

        message = (
            f"📌 Новый запрос на тату:\n"
            f"👤 Пользователь: @{user.username or 'без_ника'}\n"
        )

        if answers:  # Для ручного расчета
            message += (
                f"▸ Тип: {answers.get('type', {}).get('label', 'не указано')}\n"
                f"▸ Местоположение: {answers.get('location', {}).get('label', 'не указано')}\n"
                f"▸ Размер: {answers.get('size', {}).get('label', 'не указано')}\n"
                f"▸ Детализация: {answers.get('detail', {}).get('label', 'не указано')}\n"
            )
            if answers.get('size', {}).get('value') != "special":
                price = MINIMAL_PRICE
                for key in ['type', 'location', 'size', 'detail']:
                    price *= answers[key]['value']
                message += f"💵 Оценка: {int(price)} ₽\n"
        else:  # Для расчета по изображению
            message += (
                f"▸ Площадь: {context.user_data.get('image_area', 0):.1f} см²\n"
                f"▸ Контуров: {context.user_data.get('contours_count', 0)}\n"
                f"  Оценка: {context.user_data.get('price', 0)} ₽\n"
            )

        message += (
            f"🆔 ID: {user.id}\n"
            f"✉️ Имя: {user.first_name}"
        )
        try:
            await context.bot.send_message(chat_id=MASTER_CHAT_ID, text=message)
            await query.edit_message_text("Запрос отправлен мастеру! Ожидай ответа.")
        except Exception as e:
            # logger.error(f"Ошибка отправки: {e}")
            await query.edit_message_text("Что-то пошло не так и отправить запрос не получилось. Попробуй позже или не стесняйся и пиши сюда - @Kvarkovsky .")

        return ConversationHandler.END
    else:
        # Удаляем предыдущее сообщение с кнопками
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения: {e}")

        # Отправляем новое сообщение с кнопкой
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text="Хорошо! Нажми кнопку ниже чтобы начать новый расчет:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Давай по новой", callback_data="restart")]
            ])
        )
        return IMAGE_ANALYSIS_DONE

async def send_processed_image(bot, chat_id: int, image_np: np.ndarray, binary: np.ndarray, contours, tattoo_type: str):
    """Отправка обработанного изображения с контурами и бинаризацией"""
    try:
        # Создаем debug-изображение с тремя панелями
        debug_img1 = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)  # Бинаризация
        debug_img2 = cv2.drawContours(image_np.copy(), contours, -1, (0, 255, 0), 2)  # Контуры
        debug_image = np.hstack([image_np, debug_img1, debug_img2])
        cv2.putText(debug_image, f"Type: {tattoo_type}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Конвертируем для отправки
        debug_image_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))
        img_byte_arr = io.BytesIO()
        debug_image_pil.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        await bot.send_photo(
            chat_id=chat_id,
            photo=img_byte_arr,
            caption="Результаты обработки:\n"
                    "1. Оригинал | 2. Бинаризация | 3. Контуры\n"
                    "Если контуры выглядят неточно, попробуй другое изображение."
        )
    except Exception as e:
        logger.error(f"Ошибка создания debug-изображения: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text="Не удалось визуализировать процесс обработки."
        )


def improved_calculate_areas(binary_image, contours, px_per_cm):
    """Расчет площадей и периметра с учетом заливки"""
    try:
        # Площадь по залитым пикселям
        filled_px = np.sum(binary_image == 255)
        filled_cm2 = filled_px / (px_per_cm ** 2)

        # Площадь по контурам (используем boundingRect для каждого контура)
        contour_px = sum(w * h for (x, y, w, h) in
                        [cv2.boundingRect(cnt) for cnt in contours])
        contour_cm2 = contour_px / (px_per_cm ** 2)

        # Периметр
        perimeter = sum(cv2.arcLength(cnt, True) for cnt in contours) / px_per_cm

        # logger.debug(
        #     "Детальный расчет площадей:\n"
        #     f"Всего пикселей: {binary_image.size}\n"
        #     f"Заливка: {filled_px} px -> {filled_cm2:.2f} см²\n"
        #     f"Контуры: {contour_px} px -> {contour_cm2:.2f} см²\n"
        #     f"Соотношение: {filled_cm2 / (contour_cm2 + 1e-5):.2f}\n"
        #     f"Пикселей на см: {px_per_cm:.1f}"
        # )

        return {
            'filled': filled_cm2,
            'contour': contour_cm2,
            'perimeter': perimeter
        }
    except Exception as e:
        # logger.error(f"Ошибка расчета площадей: {str(e)}", exc_info=True)
        return {'filled': 0, 'contour': 0, 'perimeter': 0}


def calculate_price(filled_area, contour_area, perimeter, contours_count, tattoo_type=None, location_factor=1.0):
    """Расчет цены с учетом типа татуировки и местоположения"""
    try:
        # Если тип не указан, определяем автоматически
        if tattoo_type is None:
            tattoo_type = determine_tattoo_type({
                'filled': filled_area,
                'contour': contour_area
            })

        # Коэффициент сложности
        if contours_count < 15:
            complexity = 0.8
        elif contours_count < 500:
            complexity = 1.0
        else:
            complexity = 1.2

        # Расчет в зависимости от типа
        if tattoo_type == 'filled':
            price = filled_area * BASE_RATE_PER_CM2 * complexity
        elif tattoo_type == 'mixed':
            filled_price = filled_area * BASE_RATE_PER_CM2 * complexity
            contour_price = perimeter * BASE_RATE_PER_CM * complexity
            price = (filled_price + contour_price) / 2
        else:  # outline
            price = perimeter * BASE_RATE_PER_CM * complexity

        # Умножаем на коэффициент местоположения
        price *= location_factor

        return max(int(price), MINIMAL_PRICE)

    except Exception as e:
        logger.error(f"Ошибка расчета цены: {e}")
        return MINIMAL_PRICE


async def restart(update: Update, context: CallbackContext) -> int:
    """попытка номер пять"""
    query = update.callback_query
    await query.answer()

    # Очищаем данные
    context.user_data.clear()

    # Удаляем предыдущее сообщение
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

    # Отправляем новое стартовое сообщение
    keyboard = [
        [InlineKeyboardButton("Оценить по изображению", callback_data='image')],
        [InlineKeyboardButton("Ручной расчет", callback_data='manual')]
    ]
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text="Привет! Я помогу рассчитать стоимость тату. Выбери способ:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return SELECT_ACTION

async def cancel(update: Update, context: CallbackContext) -> int:
    """галя отмена"""
    await update.message.reply_text("До свидания! Если потребуется расчет - напиши /start")
    return ConversationHandler.END


async def error_handler(update: object, context: CallbackContext) -> None:
    """Обработка останков"""
    # logger.error(msg="Exception while handling an update:", exc_info=context.error)

    if update and isinstance(update, Update):
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Произошла ошибка. Пожалуйста, попробуй еще раз."
            )

def main() -> None:
    import warnings
    from telegram.warnings import PTBUserWarning
    warnings.filterwarnings("ignore", category=PTBUserWarning)
    """с богом"""
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_error_handler(error_handler)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_ACTION: [CallbackQueryHandler(select_action)],
            GET_IMAGE: [MessageHandler(filters.PHOTO, get_image)],
            GET_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_height)],
            IMAGE_QUESTION_LOCATION: [CallbackQueryHandler(handle_location_answer, pattern="^img_loc_")],
            MANUAL_QUESTION_TYPE: [CallbackQueryHandler(handle_manual_answer, pattern="^ans_0_")],
            MANUAL_QUESTION_LOCATION: [CallbackQueryHandler(handle_manual_answer, pattern="^ans_1_")],
            MANUAL_QUESTION_SIZE: [CallbackQueryHandler(handle_manual_answer, pattern="^ans_2_")],
            MANUAL_QUESTION_DETAIL: [CallbackQueryHandler(handle_manual_answer, pattern="^ans_3_")],
            IMAGE_ANALYSIS_DONE: [
                CallbackQueryHandler(handle_contact_decision, pattern="^(contact_yes|contact_no)$"),
                CallbackQueryHandler(restart, pattern="^restart$")
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_chat=True
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
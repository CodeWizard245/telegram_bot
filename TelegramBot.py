import json
import os
import logging
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Файл для хранения данных
DATA_FILE = 'financial_data.json'

def load_data():
    """Загружает данные из JSON файла или создает новый при необходимости"""
    default_data = {
        'categories': {},
        'rentals': []
    }

    if not os.path.exists(DATA_FILE):
        save_data(default_data)
        return default_data

    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as file:
            if os.stat(DATA_FILE).st_size == 0:
                save_data(default_data)
                return default_data

            data = json.load(file)
            if isinstance(data.get('categories'), list):
                data['categories'] = {cat: {"profit": 0, "expense": 0, "income": 0} for cat in data['categories']}
                save_data(data)
            return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ошибка загрузки данных: {e}")
        save_data(default_data)
        return default_data

def save_data(data):
    """Сохраняет данные в JSON файл"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"Ошибка сохранения данных: {e}")

def validate_datetime_format(dt_str):
    """Проверяет корректность формата времени 14:06-11.07.25"""
    pattern = r'^\d{2}:\d{2}-\d{2}\.\d{2}\.\d{2}$'
    if not re.match(pattern, dt_str):
        return False

    try:
        time_part, date_part = dt_str.split('-')
        day, month, year = map(int, date_part.split('.'))
        hour, minute = map(int, time_part.split(':'))
        full_year = 2000 + year
        datetime(year=full_year, month=month, day=day, hour=hour, minute=minute)
        return True
    except (ValueError, AttributeError):
        return False

async def check_rental_end_times(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет время окончания аренд и отправляет уведомления"""
    data = load_data()
    now = datetime.now()

    for rental in data['rentals']:
        try:
            if rental.get('notified', False):
                continue

            time_part, date_part = rental['end_time'].split('-')
            day, month, year = map(int, date_part.split('.'))
            hour, minute = map(int, time_part.split(':'))
            end_dt = datetime(2000 + year, month, day, hour, minute)

            # Уведомляем, если текущее время совпадает с временем окончания (в пределах 1 минуты)
            if end_dt <= now < end_dt + timedelta(minutes=1):
                message = (
                    f"⏰ Аренда {rental['category']} завершена!\n\n"
                )

                await context.bot.send_message(
                    chat_id=context.job.chat_id,
                    text=message
                )

                rental['notified'] = True
                save_data(data)

        except Exception as e:
            logger.error(f"Ошибка при проверке аренды: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    # Проверяем наличие job_queue перед использованием
    if hasattr(context, 'job_queue') and context.job_queue is not None:
        if 'job' not in context.chat_data:
            context.job_queue.run_repeating(
                check_rental_end_times,
                interval=60.0,
                first=0,
                chat_id=update.effective_chat.id,
                name=str(update.effective_chat.id)
            )
            context.chat_data['job'] = True
    else:
        logger.error("JobQueue не доступен. Убедитесь, что установлен python-telegram-bot[job-queue].")
        await update.message.reply_text(
            "⚠️ Ошибка: JobQueue не доступен. Установите python-telegram-bot с поддержкой JobQueue:\n"
            "pip install \"python-telegram-bot[job-queue]\"\n"
            "Уведомления не будут работать до исправления."
        )

    if 'action' in context.user_data:
        del context.user_data['action']
    if 'selected_category' in context.user_data:
        del context.user_data['selected_category']

    keyboard = [
        [InlineKeyboardButton("📂 Выбор Категории", callback_data='select_category')],
        [InlineKeyboardButton("➕ Добавить аренду", callback_data='select_category_for_rental')],
        [InlineKeyboardButton("⚙️ Другое", callback_data='other_options')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text('Главное меню:', reply_markup=reply_markup)
    else:
        query = update.callback_query
        await query.edit_message_text(text='Главное меню:', reply_markup=reply_markup)

async def other_options_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню дополнительных опций"""
    keyboard = [
        [InlineKeyboardButton("📝 Добавить категорию", callback_data='add_category')],
        [InlineKeyboardButton("🗑️ Удалить категорию", callback_data='delete_category')],
        [InlineKeyboardButton("↩️ Откатить аренду", callback_data='select_category_to_undo')],
        [InlineKeyboardButton("ℹ️ Информация", callback_data='info')],
        [InlineKeyboardButton("🔕 Отключить уведомления", callback_data='stop_notifications')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    query = update.callback_query
    await query.edit_message_text(text="Дополнительные опции:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий кнопок"""
    query = update.callback_query
    await query.answer()

    try:
        if query.data == 'select_category':
            await select_category_menu(update, context, mode='view')
        elif query.data == 'select_category_for_rental':
            await select_category_menu(update, context, mode='rental')
        elif query.data == 'other_options':
            await other_options_menu(update, context)
        elif query.data == 'add_category':
            context.user_data['action'] = 'add_category'
            await query.edit_message_text(text="📝 Введите название новой категории:")
        elif query.data == 'delete_category':
            await select_category_menu(update, context, mode='delete')
        elif query.data == 'select_category_to_undo':
            await select_category_menu(update, context, mode='undo')
        elif query.data == 'info':
            await show_info(update, context)
        elif query.data == 'stop_notifications':
            await stop_notifications(update, context)
        elif query.data.startswith('category_'):
            parts = query.data.split('_')
            category = '_'.join(parts[1:-1])
            mode = parts[-1]

            if mode == 'view':
                await show_category_stats(update, context, category)
            elif mode == 'rental':
                context.user_data['selected_category'] = category
                context.user_data['action'] = 'add_rental'
                await query.edit_message_text(
                    text=f"Выбрана категория: {category}\n"
                         "Введите данные в формате: [П] [Р] [Начало] [Конец]\n"
                         "Где:\n"
                         "П - прибыль (число)\n"
                         "Р - расход (число)\n"
                         "Начало - время в формате 14:06-11.07.25\n"
                         "Конец - время в формате 14:06-11.07.25\n\n"
                         "Пример: 50000 10000 14:06-11.07.25 18:00-11.07.25"
                )
            elif mode == 'delete':
                await delete_category(update, context, category)
            elif mode == 'undo':
                await show_rentals_to_undo(update, context, category)
        elif query.data.startswith('undo_'):
            rental_id = int(query.data.split('_')[1])
            await undo_rental(update, context, rental_id)
        elif query.data == 'back_to_main':
            await start(update, context)
    except Exception as e:
        logger.error(f"Ошибка в обработчике кнопок: {e}")
        await query.edit_message_text(text="⚠️ Произошла ошибка. Пожалуйста, попробуйте еще раз.")

async def select_category_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, mode='view'):
    """Меню выбора категории"""
    data = load_data()
    keyboard = []

    for category in data['categories'].keys():
        if mode == 'delete':
            text = f"🗑️ {category}"
        elif mode == 'undo':
            text = f"↩️ {category}"
        else:
            text = f"📂 {category}"

        keyboard.append([InlineKeyboardButton(text, callback_data=f'category_{category}_{mode}')])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='other_options' if mode in ['delete',
                                                                                               'undo'] else 'back_to_main')])
    reply_markup = InlineKeyboardMarkup(keyboard)

    title = {
        'view': "📂 Выберите категорию для просмотра",
        'rental': "➕ Выберите категорию для аренды",
        'delete': "🗑️ Выберите категорию для удаления",
        'undo': "↩️ Выберите категорию для отката аренды"
    }.get(mode, "Выберите категорию")

    query = update.callback_query
    await query.edit_message_text(text=title, reply_markup=reply_markup)

async def show_category_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    """Показывает статистику по категории"""
    data = load_data()
    rentals = [r for r in data['rentals'] if r.get('category') == category]
    total_profit = sum(r['profit'] for r in rentals)
    total_expense = sum(r['expense'] for r in rentals)
    total_income = total_profit - total_expense

    rentals_list = "\n".join(
        f"{i + 1}. {r['start_time']}-{r['end_time']} "
        f"Прибыль: {r['profit']} Расход: {r['expense']} Доход: {r['income']}"
        for i, r in enumerate(rentals[-5:]))

    text = (
        f"📊 Категория: {category}\n\n"
        f"💰 Общая прибыль: {total_profit:.2f}\n"
        f"💸 Общие расходы: {total_expense:.2f}\n"
        f"💵 Общий доход: {total_income:.2f}\n\n"
        f"📂 Всего аренд: {len(rentals)}\n\n"
        f"Последние аренды:\n{rentals_list if rentals else 'Нет аренд'}"
    )

    keyboard = [
        [InlineKeyboardButton("🔙 Назад к категориям", callback_data='select_category')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    query = update.callback_query
    await query.edit_message_text(text=text, reply_markup=reply_markup)

async def show_rentals_to_undo(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    """Показывает последние аренды для отката"""
    data = load_data()
    rentals = [r for r in data['rentals'] if r.get('category') == category][-5:]

    if not rentals:
        await update.callback_query.edit_message_text(
            text=f"В категории '{category}' нет аренд для отката."
        )
        return

    text = "↩️ Выберите аренду для отката:\n\n" + "\n".join(
        f"{i + 1}. {r['start_time']}-{r['end_time']} "
        f"Прибыль: {r['profit']} Расход: {r['expense']}"
        for i, r in enumerate(reversed(rentals)))

    keyboard = [
        [InlineKeyboardButton(f"↩️ Откатить аренду {i + 1}",
                              callback_data=f'undo_{len(data["rentals"]) - len(rentals) + i}')]
        for i in range(len(rentals))
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='select_category_to_undo')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)

async def undo_rental(update: Update, context: ContextTypes.DEFAULT_TYPE, rental_id: int):
    """Откатывает указанную аренду"""
    data = load_data()

    try:
        rental = data['rentals'][rental_id]
        category = rental['category']

        if category in data['categories']:
            data['categories'][category]['profit'] -= rental['profit']
            data['categories'][category]['expense'] -= rental['expense']
            data['categories'][category]['income'] -= rental['income']

        del data['rentals'][rental_id]
        save_data(data)

        await update.callback_query.edit_message_text(
            text=f"✅ Аренда успешно откачена:\n\n"
                 f"Категория: {category}\n"
                 f"Время: {rental['start_time']}-{rental['end_time']}\n"
                 f"Прибыль: -{rental['profit']}\n"
                 f"Расход: -{rental['expense']}"
        )
    except (IndexError, KeyError) as e:
        logger.error(f"Ошибка отката аренды: {e}")
        await update.callback_query.edit_message_text(
            text="⚠️ Не удалось откатить аренду. Попробуйте снова."
        )

async def delete_category(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    """Удаление категории"""
    data = load_data()

    if category in data['categories']:
        del data['categories'][category]
        data['rentals'] = [r for r in data['rentals'] if r.get('category') != category]
        save_data(data)

        query = update.callback_query
        await query.edit_message_text(text=f"✅ Категория '{category}' и связанные аренды удалены.")
    else:
        query = update.callback_query
        await query.edit_message_text(text="⚠️ Категория не найдена.")

async def show_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ информации"""
    text = (
        "📋 Информация:\n\n"
        "П - прибыль (доход от аренды)\n"
        "Р - расход (затраты на обслуживание)\n"
        "Начало - время начала в формате 14:06-11.07.25\n"
        "Конец - время окончания в формате 14:06-11.07.25\n"
        "Д - доход (рассчитывается автоматически как П - Р)\n\n"
        "Пример ввода аренды:\n"
        "50000 10000 14:06-11.07.25 18:00-11.07.25\n\n"
        "Бот пришлет уведомление в момент окончания аренды"
    )

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='other_options')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    query = update.callback_query
    await query.edit_message_text(text=text, reply_markup=reply_markup)

async def stop_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановка уведомлений"""
    if hasattr(context, 'job_queue') and context.job_queue is not None:
        current_jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
        for job in current_jobs:
            job.schedule_removal()

    if 'job' in context.chat_data:
        del context.chat_data['job']

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text="🔕 Уведомления отключены")
    else:
        await update.message.reply_text("🔕 Уведомления отключены")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_data = context.user_data
    text = update.message.text.strip()

    try:
        if 'action' in user_data:
            if user_data['action'] == 'add_category':
                data = load_data()
                if text not in data['categories']:
                    data['categories'][text] = {"profit": 0, "expense": 0, "income": 0}
                    save_data(data)
                    await update.message.reply_text(f"✅ Категория '{text}' успешно добавлена!")
                    await start(update, context)
                else:
                    await update.message.reply_text("⚠️ Эта категория уже существует. Введите другое название:")
                return

            elif user_data['action'] == 'add_rental':
                if 'selected_category' not in user_data:
                    await update.message.reply_text("⚠️ Ошибка: категория не выбрана. Попробуйте снова.")
                    await start(update, context)
                    return

                try:
                    parts = text.split()
                    if len(parts) == 4:
                        profit = float(parts[0])
                        expense = float(parts[1])
                        start_time = parts[2]
                        end_time = parts[3]

                        if not validate_datetime_format(start_time):
                            await update.message.reply_text(
                                "⚠️ Неверный формат времени начала!\n"
                                "Используйте формат: 14:06-11.07.25\n"
                                "Пример: 14:06-11.07.25"
                            )
                            return

                        if not validate_datetime_format(end_time):
                            await update.message.reply_text(
                                "⚠️ Неверный формат времени окончания!\n"
                                "Используйте формат: 14:06-11.07.25\n"
                                "Пример: 18:00-11.07.25"
                            )
                            return

                        def parse_dt(dt_str):
                            time_part, date_part = dt_str.split('-')
                            day, month, year = map(int, date_part.split('.'))
                            hour, minute = map(int, time_part.split(':'))
                            return datetime(2000 + year, month, day, hour, minute)

                        start_dt = parse_dt(start_time)
                        end_dt = parse_dt(end_time)

                        if end_dt <= start_dt:
                            await update.message.reply_text("⚠️ Время окончания должно быть позже времени начала!")
                            return

                        category = user_data['selected_category']
                        income = profit - expense

                        data = load_data()
                        data['rentals'].append({
                            'category': category,
                            'profit': profit,
                            'expense': expense,
                            'start_time': start_time,
                            'end_time': end_time,
                            'income': income,
                            'notified': False
                        })

                        if category in data['categories']:
                            data['categories'][category]['profit'] += profit
                            data['categories'][category]['expense'] += expense
                            data['categories'][category]['income'] += income

                        save_data(data)

                        await update.message.reply_text(
                            f"✅ Аренда успешно добавлена в категорию '{category}':\n\n"
                            f"💰 Прибыль: {profit:.2f}\n"
                            f"💸 Расход: {expense:.2f}\n"
                            f"💵 Доход: {income:.2f}\n"
                            f"⏱️ Время: {start_time} - {end_time}\n\n"
                            f"⏰ Бот пришлет уведомление в момент окончания аренды"
                        )
                        await start(update, context)
                    else:
                        await update.message.reply_text(
                            "⚠️ Неверный формат. Введите данные как:\n"
                            "[П] [Р] [Начало] [Конец]\n"
                            "Пример: 50000 10000 14:06-11.07.25 18:00-11.07.25"
                        )
                except ValueError:
                    await update.message.reply_text(
                        "⚠️ Ошибка в данных. Убедитесь, что:\n"
                        "- Прибыль (П) и расход (Р) - числа\n"
                        "- Время в формате 14:06-11.07.25\n"
                        "Попробуйте снова:"
                    )
                return
    except Exception as e:
        logger.error(f"Ошибка обработки текста: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка. Пожалуйста, попробуйте еще раз.")

    await start(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(msg="Исключение при обработке запроса:", exc_info=context.error)

    try:
        if isinstance(update, Update):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Произошла ошибка. Пожалуйста, попробуйте позже."
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")

def main():
    """Запуск бота"""
    if not os.path.exists(DATA_FILE):
        save_data({'categories': {}, 'rentals': []})

    # Убедитесь, что заменили YOUR_BOT_TOKEN на реальный токен вашего бота!
    TOKEN = '8117449778:AAFBTyihd8N4ZfiMH9IHDQ6BrUMcHU4xYGc'  # ← ЗАМЕНИТЕ ЭТО НА ВАШ РЕАЛЬНЫЙ ТОКЕН

    if TOKEN == 'YOUR_BOT_TOKEN' or not TOKEN:
        logger.error("Необходимо указать реальный токен бота!")
        print("Пожалуйста, укажите реальный токен бота в переменной TOKEN!")
        return

    # Создаем Application с явным указанием job_queue
    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop_notifications", stop_notifications))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(error_handler)

    logger.info("Бот запущен...")
    print("Бот успешно запущен. Для остановки нажмите Ctrl+C")
    application.run_polling()

if __name__ == '__main__':
    # Проверяем установлены ли все зависимости
    try:
        from telegram.ext import JobQueue
        main()
    except ImportError:
        print("Необходимо установить python-telegram-bot с поддержкой JobQueue:")
        print('pip install "python-telegram-bot[job-queue]"')
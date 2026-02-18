"""
Телеграм Казино Бот v3.0
Пример работы от @kx_de

ВНИМАНИЕ: Это демонстрационный бот для обучения
Для production требуется серьезная доработка
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import random
import logging
import sqlite3
from datetime import datetime
import asyncio 
import os                          # ← добавили
 
from dotenv import load_dotenv
import os

# и только потом
load_dotenv()                  # ← теперь это сработает

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения! ...")
ADMIN_ID = 8549130203  # Ваш Telegram ID (узнать: @userinfobot)
# ======================================

# Константы
START_BALANCE = 10000
MIN_BET = 100
MAX_BET = 5000

class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self, db_name='casino_bot.db'):
        self.db_name = db_name
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_name)
    
    def init_db(self):
        """Инициализация базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 10000,
                games_played INTEGER DEFAULT 0,
                total_won INTEGER DEFAULT 0,
                total_lost INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_played TIMESTAMP
            )
        ''')
        
        # Таблица истории игр
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS games_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_type TEXT,
                bet INTEGER,
                result TEXT,
                multiplier REAL,
                profit INTEGER,
                balance_after INTEGER,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица промокодов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                amount INTEGER,
                max_uses INTEGER,
                current_uses INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица использованных промокодов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS used_promocodes (
                user_id INTEGER,
                code TEXT,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, code)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id, username=None):
        """Получить данные пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute('''
                INSERT INTO users (user_id, username, balance)
                VALUES (?, ?, ?)
            ''', (user_id, username, START_BALANCE))
            conn.commit()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
        
        conn.close()
        return user
    
    def update_balance(self, user_id, amount):
        """Обновить баланс пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users 
            SET balance = balance + ?,
                games_played = games_played + 1,
                total_won = total_won + CASE WHEN ? > 0 THEN ? ELSE 0 END,
                total_lost = total_lost + CASE WHEN ? < 0 THEN ABS(?) ELSE 0 END,
                last_played = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (amount, amount, amount, amount, amount, user_id))
        
        conn.commit()
        conn.close()
    
    def add_game_history(self, user_id, game_type, bet, result, multiplier, profit, balance_after):
        """Добавить запись в историю игр"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO games_history 
            (user_id, game_type, bet, result, multiplier, profit, balance_after)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, game_type, bet, result, multiplier, profit, balance_after))
        
        conn.commit()
        conn.close()
    
    def get_user_history(self, user_id, limit=10):
        """Получить историю игр пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT game_type, bet, result, multiplier, profit, played_at
            FROM games_history
            WHERE user_id = ?
            ORDER BY played_at DESC
            LIMIT ?
        ''', (user_id, limit))
        
        history = cursor.fetchall()
        conn.close()
        return history
    
    def get_top_players(self, limit=10):
        """Получить топ игроков по балансу"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT username, balance, games_played, total_won
            FROM users
            ORDER BY balance DESC
            LIMIT ?
        ''', (limit,))
        
        top = cursor.fetchall()
        conn.close()
        return top
    
    def get_all_users(self):
        """Получить всех пользователей для рассылки"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        conn.close()
        return [user[0] for user in users]
    
    def get_stats(self):
        """Получить общую статистику бота"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(balance) FROM users')
        total_balance = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM games_history')
        total_games = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(profit) FROM games_history WHERE result = "win"')
        total_won = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(ABS(profit)) FROM games_history WHERE result = "lose"')
        total_lost = cursor.fetchone()[0] or 0
        
        conn.close()
        return {
            'users': total_users,
            'balance': total_balance,
            'games': total_games,
            'won': total_won,
            'lost': total_lost
        }
    
    # Промокоды
    def create_promocode(self, code, amount, max_uses):
        """Создать промокод"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO promocodes (code, amount, max_uses)
                VALUES (?, ?, ?)
            ''', (code.upper(), amount, max_uses))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False
    
    def use_promocode(self, user_id, code):
        """Использовать промокод"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Проверяем существование промокода
        cursor.execute('SELECT * FROM promocodes WHERE code = ?', (code.upper(),))
        promo = cursor.fetchone()
        
        if not promo:
            conn.close()
            return None, "Промокод не найден"
        
        code_text, amount, max_uses, current_uses, created_at = promo
        
        # Проверяем лимит использований
        if current_uses >= max_uses:
            conn.close()
            return None, "Промокод исчерпан"
        
        # Проверяем, использовал ли пользователь этот промокод
        cursor.execute('''
            SELECT * FROM used_promocodes 
            WHERE user_id = ? AND code = ?
        ''', (user_id, code.upper()))
        
        if cursor.fetchone():
            conn.close()
            return None, "Вы уже использовали этот промокод"
        
        # Применяем промокод
        cursor.execute('''
            UPDATE promocodes 
            SET current_uses = current_uses + 1
            WHERE code = ?
        ''', (code.upper(),))
        
        cursor.execute('''
            INSERT INTO used_promocodes (user_id, code)
            VALUES (?, ?)
        ''', (user_id, code.upper()))
        
        cursor.execute('''
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
        ''', (amount, user_id))
        
        conn.commit()
        conn.close()
        return amount, "Успешно активирован"
    
    def get_all_promocodes(self):
        """Получить все промокоды"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM promocodes ORDER BY created_at DESC')
        promos = cursor.fetchall()
        conn.close()
        return promos
    
    def delete_promocode(self, code):
        """Удалить промокод"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM promocodes WHERE code = ?', (code.upper(),))
        deleted = cursor.rowcount > 0
        
        conn.commit()
        conn.close()
        return deleted

# Инициализация базы данных
db = Database()

# Хранилище активных игр
active_games = {}

def is_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    return user_id == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    user_data = db.get_user(user.id, user.username)
    balance = user_data[2]
    
    keyboard = [
        [InlineKeyboardButton("🎰 Мины", callback_data='game_mines')],
        [InlineKeyboardButton("🚀 Ракета", callback_data='game_rocket')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("🎁 Промокод", callback_data='promocode')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data='top')],
    ]
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ АДМИН-ПАНЕЛЬ", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"🎮 Казино Бот v3.0\n"
    text += f"Пример работы от @kx_de\n\n"
    text += f"👤 Привет, {user.first_name}!\n"
    text += f"💰 Баланс: {balance:,} коинов\n\n"
    text += f"⚡️ Выберите игру или действие:"
    
    await update.message.reply_text(text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    username = query.from_user.username
    
    if data == 'balance':
        await show_balance(query, user_id)
    elif data == 'stats':
        await show_stats(query, user_id)
    elif data == 'top':
        await show_top_players(query)
    elif data == 'promocode':
        await show_promocode_menu(query, user_id)
    elif data == 'game_mines':
        await game_mines_select_mines(query, user_id)
    elif data == 'game_rocket':
        await game_rocket_start(query, user_id)
    elif data.startswith('mines_count_'):
        mines_count = int(data.split('_')[2])
        await game_mines_select_bet(query, user_id, mines_count)
    elif data.startswith('mines_bet_'):
        parts = data.split('_')
        mines_count = int(parts[2])
        bet = int(parts[3])
        await start_mines_game(query, user_id, mines_count, bet)
    elif data.startswith('mines_click_'):
        cell = int(data.split('_')[2])
        await process_mines_click(query, user_id, cell)
    elif data == 'mines_cashout':
        await mines_cashout(query, user_id)
    elif data.startswith('rocket_bet_'):
        bet = int(data.split('_')[2])
        await start_rocket_game(query, user_id, bet, context)
    elif data == 'rocket_cashout':
        await rocket_cashout(query, user_id)
    elif data == 'admin_panel':
        if is_admin(user_id):
            await show_admin_panel(query)
    elif data == 'admin_broadcast':
        if is_admin(user_id):
            await start_broadcast(query, context)
    elif data == 'admin_stats':
        if is_admin(user_id):
            await show_admin_stats(query)
    elif data == 'admin_promocodes':
        if is_admin(user_id):
            await show_admin_promocodes(query)
    elif data == 'admin_create_promo':
        if is_admin(user_id):
            await start_create_promocode(query, context)
    elif data.startswith('admin_delete_promo_'):
        if is_admin(user_id):
            code = data.replace('admin_delete_promo_', '')
            await delete_promocode(query, code)
    elif data == 'main_menu':
        await show_main_menu(query, user_id, username)

async def show_balance(query, user_id):
    """Показать баланс"""
    user_data = db.get_user(user_id)
    balance = user_data[2]
    games = user_data[3]
    
    text = f"💰 ВАШ БАЛАНС\n\n"
    text += f"💵 Текущий баланс: {balance:,} коинов\n"
    text += f"🎮 Игр сыграно: {games}\n"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_stats(query, user_id):
    """Показать статистику"""
    user_data = db.get_user(user_id)
    balance = user_data[2]
    games = user_data[3]
    total_won = user_data[4]
    total_lost = user_data[5]
    
    history = db.get_user_history(user_id, 5)
    
    text = f"📊 ВАША СТАТИСТИКА\n\n"
    text += f"💰 Баланс: {balance:,} коинов\n"
    text += f"🎮 Игр сыграно: {games}\n"
    text += f"✅ Всего выиграно: {total_won:,} коинов\n"
    text += f"❌ Всего проиграно: {total_lost:,} коинов\n"
    text += f"📈 Чистая прибыль: {total_won - total_lost:,} коинов\n\n"
    
    if history:
        text += "📜 Последние 5 игр:\n"
        for game in history:
            game_type, bet, result, multiplier, profit, played_at = game
            emoji = "✅" if result == "win" else "❌"
            text += f"{emoji} {game_type}: {bet}, "
            text += f"x{multiplier:.2f}, " if multiplier else ""
            text += f"{'+' if profit > 0 else ''}{profit}\n"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_top_players(query):
    """Показать топ игроков"""
    top = db.get_top_players(10)
    
    text = "🏆 ТОП-10 ИГРОКОВ\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    for i, player in enumerate(top, 1):
        username, balance, games, total_won = player
        medal = medals[i-1] if i <= 3 else f"{i}."
        username_display = username if username else "Аноним"
        text += f"{medal} @{username_display}\n"
        text += f"   💰 {balance:,} | 🎮 {games} игр | ✅ +{total_won:,}\n\n"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_promocode_menu(query, user_id):
    """Меню промокодов"""
    text = "🎁 ПРОМОКОДЫ\n\n"
    text += "Введите промокод, чтобы получить бонус!\n\n"
    text += "Отправьте промокод в чат боту."
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_main_menu(query, user_id, username):
    """Показать главное меню"""
    user_data = db.get_user(user_id, username)
    balance = user_data[2]
    
    keyboard = [
        [InlineKeyboardButton("🎰 Мины", callback_data='game_mines')],
        [InlineKeyboardButton("🚀 Ракета", callback_data='game_rocket')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("🎁 Промокод", callback_data='promocode')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data='top')],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ АДМИН-ПАНЕЛЬ", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"🎮 Казино Бот v3.0\n"
    text += f"Пример работы от @kx_de\n\n"
    text += f"💰 Баланс: {balance:,} коинов\n\n"
    text += f"⚡️ Выберите действие:"
    
    await query.edit_message_text(text, reply_markup=reply_markup)

# ============================================
# ИГРА МИНЫ
# ============================================

async def game_mines_select_mines(query, user_id):
    """Выбор количества мин"""
    user_data = db.get_user(user_id)
    balance = user_data[2]
    
    text = f"🎰 МИНЫ\n\n"
    text += f"💰 Баланс: {balance:,} коинов\n\n"
    text += f"Выберите количество мин на поле (12 клеток):\n\n"
    text += f"⚠️ Больше мин = больше риск = больше выигрыш!"
    
    keyboard = [
        [
            InlineKeyboardButton("💣 3 мины", callback_data='mines_count_3'),
            InlineKeyboardButton("💣 4 мины", callback_data='mines_count_4')
        ],
        [
            InlineKeyboardButton("💣 5 мин", callback_data='mines_count_5'),
            InlineKeyboardButton("💣 6 мин", callback_data='mines_count_6')
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def game_mines_select_bet(query, user_id, mines_count):
    """Выбор ставки"""
    user_data = db.get_user(user_id)
    balance = user_data[2]
    
    text = f"🎰 МИНЫ ({mines_count} мин)\n\n"
    text += f"💰 Баланс: {balance:,} коинов\n\n"
    text += f"Выберите ставку:"
    
    keyboard = [
        [
            InlineKeyboardButton("100 💎", callback_data=f'mines_bet_{mines_count}_100'),
            InlineKeyboardButton("500 💎", callback_data=f'mines_bet_{mines_count}_500')
        ],
        [
            InlineKeyboardButton("1000 💎", callback_data=f'mines_bet_{mines_count}_1000'),
            InlineKeyboardButton("2000 💎", callback_data=f'mines_bet_{mines_count}_2000')
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data='game_mines')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def start_mines_game(query, user_id, mines_count, bet):
    """Начать игру в мины"""
    user_data = db.get_user(user_id)
    balance = user_data[2]
    
    if balance < bet:
        await query.answer("❌ Недостаточно коинов!", show_alert=True)
        return
    
    # Создаем поле 3x4 = 12 клеток
    total_cells = 12
    mine_positions = random.sample(range(total_cells), mines_count)
    
    # Сохраняем игру
    active_games[user_id] = {
        'type': 'mines',
        'bet': bet,
        'mines_count': mines_count,
        'mine_positions': mine_positions,
        'opened_cells': [],
        'multiplier': 1.0,
        'balance_before': balance
    }
    
    # Вычитаем ставку
    db.update_balance(user_id, -bet)
    
    text = f"🎰 МИНЫ ({mines_count} мин)\n\n"
    text += f"💰 Ставка: {bet:,} коинов\n"
    text += f"📈 Множитель: x1.00\n"
    text += f"💵 Текущий выигрыш: {bet:,}\n\n"
    text += f"🎯 Открыто: 0/{total_cells - mines_count}\n\n"
    text += f"Выберите клетку:"
    
    keyboard = create_mines_keyboard(user_id)
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

def create_mines_keyboard(user_id):
    """Создать клавиатуру для игры в мины"""
    game = active_games.get(user_id)
    if not game:
        return []
    
    opened = game['opened_cells']
    mines = game['mine_positions']
    
    keyboard = []
    for row in range(3):
        buttons = []
        for col in range(4):
            cell = row * 4 + col
            if cell in opened:
                buttons.append(InlineKeyboardButton("✅", callback_data=f'mines_click_{cell}'))
            else:
                buttons.append(InlineKeyboardButton("⬜️", callback_data=f'mines_click_{cell}'))
        keyboard.append(buttons)
    
    # Кнопка забрать выигрыш
    if len(opened) > 0:
        keyboard.append([InlineKeyboardButton("💰 ЗАБРАТЬ ВЫИГРЫШ", callback_data='mines_cashout')])
    
    keyboard.append([InlineKeyboardButton("❌ Выйти", callback_data='main_menu')])
    
    return keyboard

async def process_mines_click(query, user_id, cell):
    """Обработка клика по клетке"""
    game = active_games.get(user_id)
    if not game or game['type'] != 'mines':
        await query.answer("Игра не найдена!", show_alert=True)
        return
    
    if cell in game['opened_cells']:
        await query.answer("Эта клетка уже открыта!", show_alert=True)
        return
    
    # Проверяем, мина ли это
    if cell in game['mine_positions']:
        # ПРОИГРЫШ
        game['opened_cells'].append(cell)
        
        result_text = f"🎰 МИНЫ - ПРОИГРЫШ! 💥\n\n"
        result_text += f"💰 Ставка: {game['bet']:,} коинов\n"
        result_text += f"💣 Вы попали на мину!\n"
        result_text += f"💵 Потеря: -{game['bet']:,} коинов\n\n"
        result_text += f"💰 Новый баланс: {db.get_user(user_id)[2]:,} коинов"
        
        # Показываем поле с минами
        field_text = "\n\nПоле:\n"
        for row in range(3):
            row_text = ""
            for col in range(4):
                c = row * 4 + col
                if c in game['mine_positions']:
                    row_text += "💣 "
                elif c in game['opened_cells']:
                    row_text += "✅ "
                else:
                    row_text += "⬜️ "
            field_text += row_text + "\n"
        result_text += field_text
        
        db.add_game_history(user_id, "Мины", game['bet'], "lose", 0, -game['bet'], db.get_user(user_id)[2])
        
        del active_games[user_id]
        
        keyboard = [
            [InlineKeyboardButton("🔄 Играть снова", callback_data='game_mines')],
            [InlineKeyboardButton("◀️ Меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(result_text, reply_markup=reply_markup)
        return
    
    # Безопасная клетка
    game['opened_cells'].append(cell)
    
    # Рассчитываем множитель
    safe_cells = 12 - game['mines_count']
    opened_count = len(game['opened_cells'])
    
    # Множитель увеличивается с каждой открытой клеткой
    # Формула: базовый множитель зависит от количества мин
    base_mult = 1 + (game['mines_count'] * 0.15)
    game['multiplier'] = base_mult * (1 + opened_count * 0.2)
    
    current_win = int(game['bet'] * game['multiplier'])
    
    # Проверяем, открыты ли все безопасные клетки
    if opened_count == safe_cells:
        # ПОБЕДА - все клетки открыты
        profit = current_win - game['bet']
        db.update_balance(user_id, current_win)
        
        result_text = f"🎰 МИНЫ - ПОБЕДА! 🎉\n\n"
        result_text += f"💰 Ставка: {game['bet']:,} коинов\n"
        result_text += f"📈 Финальный множитель: x{game['multiplier']:.2f}\n"
        result_text += f"🏆 Выигрыш: {current_win:,} коинов\n"
        result_text += f"💵 Прибыль: +{profit:,} коинов\n\n"
        result_text += f"✅ Вы открыли все безопасные клетки!\n\n"
        result_text += f"💰 Новый баланс: {db.get_user(user_id)[2]:,} коинов"
        
        db.add_game_history(user_id, "Мины", game['bet'], "win", game['multiplier'], profit, db.get_user(user_id)[2])
        
        del active_games[user_id]
        
        keyboard = [
            [InlineKeyboardButton("🔄 Играть снова", callback_data='game_mines')],
            [InlineKeyboardButton("◀️ Меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(result_text, reply_markup=reply_markup)
        return
    
    # Продолжаем игру
    text = f"🎰 МИНЫ ({game['mines_count']} мин)\n\n"
    text += f"💰 Ставка: {game['bet']:,} коинов\n"
    text += f"📈 Множитель: x{game['multiplier']:.2f}\n"
    text += f"💵 Текущий выигрыш: {current_win:,}\n\n"
    text += f"🎯 Открыто: {opened_count}/{safe_cells}\n\n"
    text += f"✅ Безопасная клетка! Продолжайте!"
    
    keyboard = create_mines_keyboard(user_id)
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def mines_cashout(query, user_id):
    """Забрать выигрыш в минах"""
    game = active_games.get(user_id)
    if not game or game['type'] != 'mines':
        await query.answer("Игра не найдена!", show_alert=True)
        return
    
    current_win = int(game['bet'] * game['multiplier'])
    profit = current_win - game['bet']
    
    db.update_balance(user_id, current_win)
    
    result_text = f"🎰 МИНЫ - ВЫИГРЫШ ЗАБРАН! 💰\n\n"
    result_text += f"💰 Ставка: {game['bet']:,} коинов\n"
    result_text += f"📈 Множитель: x{game['multiplier']:.2f}\n"
    result_text += f"🏆 Выигрыш: {current_win:,} коинов\n"
    result_text += f"💵 Прибыль: +{profit:,} коинов\n\n"
    result_text += f"💰 Новый баланс: {db.get_user(user_id)[2]:,} коинов"
    
    db.add_game_history(user_id, "Мины", game['bet'], "win", game['multiplier'], profit, db.get_user(user_id)[2])
    
    del active_games[user_id]
    
    keyboard = [
        [InlineKeyboardButton("🔄 Играть снова", callback_data='game_mines')],
        [InlineKeyboardButton("◀️ Меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(result_text, reply_markup=reply_markup)

# ============================================
# ИГРА РАКЕТА
# ============================================

async def game_rocket_start(query, user_id):
    """Начать игру в ракету - выбор ставки"""
    user_data = db.get_user(user_id)
    balance = user_data[2]
    
    text = f"🚀 РАКЕТА\n\n"
    text += f"💰 Баланс: {balance:,} коинов\n\n"
    text += f"Ракета взлетает с множителем!\n"
    text += f"Каждую секунду множитель растет.\n"
    text += f"Но ракета может взорваться в любой момент!\n\n"
    text += f"Выберите ставку:"
    
    keyboard = [
        [
            InlineKeyboardButton("100 💎", callback_data='rocket_bet_100'),
            InlineKeyboardButton("500 💎", callback_data='rocket_bet_500')
        ],
        [
            InlineKeyboardButton("1000 💎", callback_data='rocket_bet_1000'),
            InlineKeyboardButton("2000 💎", callback_data='rocket_bet_2000')
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def start_rocket_game(query, user_id, bet, context):
    """Запустить игру ракета"""
    user_data = db.get_user(user_id)
    balance = user_data[2]
    
    if balance < bet:
        await query.answer("❌ Недостаточно коинов!", show_alert=True)
        return
    
    # Вычитаем ставку
    db.update_balance(user_id, -bet)
    
    # Определяем, на каком множителе ракета взорвется
    # Шанс на 2x = 50%, на 3x = 33%, на 4x = 25% и т.д.
    explosion_multiplier = random.choices(
        [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0],
        weights=[20, 25, 20, 15, 10, 5, 3, 2]
    )[0]
    
    # Сохраняем игру
    active_games[user_id] = {
        'type': 'rocket',
        'bet': bet,
        'multiplier': 1.0,
        'explosion_multiplier': explosion_multiplier,
        'is_flying': True,
        'message_id': query.message.message_id,
        'chat_id': query.message.chat_id
    }
    
    # Запускаем полет ракеты
    asyncio.create_task(rocket_fly(user_id, context))
    
    text = f"🚀 РАКЕТА ВЗЛЕТАЕТ!\n\n"
    text += f"💰 Ставка: {bet:,} коинов\n"
    text += f"📈 Множитель: x1.00\n"
    text += f"💵 Текущий выигрыш: {bet:,}\n\n"
    text += f"⏱ Ракета летит..."
    
    keyboard = [
        [InlineKeyboardButton("💰 ЗАБРАТЬ ВЫИГРЫШ", callback_data='rocket_cashout')],
        [InlineKeyboardButton("❌ Выход", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def rocket_fly(user_id, context):
    """Процесс полета ракеты"""
    game = active_games.get(user_id)
    if not game or game['type'] != 'rocket':
        return
    
    while game['is_flying'] and game['multiplier'] < game['explosion_multiplier']:
        await asyncio.sleep(1)
        
        game = active_games.get(user_id)
        if not game or not game['is_flying']:
            break
        
        # Увеличиваем множитель каждую секунду
        game['multiplier'] += 0.1
        game['multiplier'] = round(game['multiplier'], 2)
        
        current_win = int(game['bet'] * game['multiplier'])
        
        text = f"🚀 РАКЕТА ЛЕТИТ!\n\n"
        text += f"💰 Ставка: {game['bet']:,} коинов\n"
        text += f"📈 Множитель: x{game['multiplier']:.2f}\n"
        text += f"💵 Текущий выигрыш: {current_win:,}\n\n"
        text += f"⏱ Ракета набирает высоту..."
        
        keyboard = [
            [InlineKeyboardButton("💰 ЗАБРАТЬ ВЫИГРЫШ", callback_data='rocket_cashout')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await context.bot.edit_message_text(
                chat_id=game['chat_id'],
                message_id=game['message_id'],
                text=text,
                reply_markup=reply_markup
            )
        except:
            break
    
    # Ракета взорвалась
    game = active_games.get(user_id)
    if game and game['is_flying']:
        result_text = f"🚀 РАКЕТА ВЗОРВАЛАСЬ! 💥\n\n"
        result_text += f"💰 Ставка: {game['bet']:,} коинов\n"
        result_text += f"💣 Взрыв на x{game['explosion_multiplier']:.2f}\n"
        result_text += f"💵 Потеря: -{game['bet']:,} коинов\n\n"
        result_text += f"💰 Новый баланс: {db.get_user(user_id)[2]:,} коинов"
        
        db.add_game_history(user_id, "Ракета", game['bet'], "lose", 0, -game['bet'], db.get_user(user_id)[2])
        
        keyboard = [
            [InlineKeyboardButton("🔄 Играть снова", callback_data='game_rocket')],
            [InlineKeyboardButton("◀️ Меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await context.bot.edit_message_text(
                chat_id=game['chat_id'],
                message_id=game['message_id'],
                text=result_text,
                reply_markup=reply_markup
            )
        except:
            pass
        
        if user_id in active_games:
            del active_games[user_id]

async def rocket_cashout(query, user_id):
    """Забрать выигрыш в ракете"""
    game = active_games.get(user_id)
    if not game or game['type'] != 'rocket':
        await query.answer("Игра не найдена!", show_alert=True)
        return
    
    if not game['is_flying']:
        await query.answer("Ракета уже взорвалась!", show_alert=True)
        return
    
    # Останавливаем полет
    game['is_flying'] = False
    
    current_win = int(game['bet'] * game['multiplier'])
    profit = current_win - game['bet']
    
    db.update_balance(user_id, current_win)
    
    result_text = f"🚀 ВЫИГРЫШ ЗАБРАН! 💰\n\n"
    result_text += f"💰 Ставка: {game['bet']:,} коинов\n"
    result_text += f"📈 Множитель: x{game['multiplier']:.2f}\n"
    result_text += f"🏆 Выигрыш: {current_win:,} коинов\n"
    result_text += f"💵 Прибыль: +{profit:,} коинов\n\n"
    result_text += f"💰 Новый баланс: {db.get_user(user_id)[2]:,} коинов"
    
    db.add_game_history(user_id, "Ракета", game['bet'], "win", game['multiplier'], profit, db.get_user(user_id)[2])
    
    del active_games[user_id]
    
    keyboard = [
        [InlineKeyboardButton("🔄 Играть снова", callback_data='game_rocket')],
        [InlineKeyboardButton("◀️ Меню", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(result_text, reply_markup=reply_markup)

# ============================================
# АДМИН-ПАНЕЛЬ
# ============================================

async def show_admin_panel(query):
    """Показать админ-панель"""
    text = "⚙️ АДМИН-ПАНЕЛЬ\n\n"
    text += "Управление ботом:"
    
    keyboard = [
        [InlineKeyboardButton("📢 Рассылка всем", callback_data='admin_broadcast')],
        [InlineKeyboardButton("📊 Статистика бота", callback_data='admin_stats')],
        [InlineKeyboardButton("🎁 Промокоды", callback_data='admin_promocodes')],
        [InlineKeyboardButton("◀️ Назад", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_admin_stats(query):
    """Показать статистику бота"""
    stats = db.get_stats()
    
    text = "📊 СТАТИСТИКА БОТА\n\n"
    text += f"👥 Всего пользователей: {stats['users']}\n"
    text += f"💰 Общий баланс: {stats['balance']:,} коинов\n"
    text += f"🎮 Всего игр: {stats['games']}\n"
    text += f"✅ Выиграно: {stats['won']:,} коинов\n"
    text += f"❌ Проиграно: {stats['lost']:,} коинов\n"
    text += f"📈 Прибыль казино: {stats['lost'] - stats['won']:,} коинов\n"
    
    keyboard = [[InlineKeyboardButton("◀️ Админ-панель", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def show_admin_promocodes(query):
    """Показать список промокодов"""
    promos = db.get_all_promocodes()
    
    text = "🎁 ПРОМОКОДЫ\n\n"
    
    if promos:
        for promo in promos:
            code, amount, max_uses, current_uses, created_at = promo
            text += f"📌 {code}\n"
            text += f"   💰 Сумма: {amount:,}\n"
            text += f"   👥 Использовано: {current_uses}/{max_uses}\n\n"
    else:
        text += "Промокодов пока нет.\n\n"
    
    text += "Выберите действие:"
    
    keyboard = [[InlineKeyboardButton("➕ Создать промокод", callback_data='admin_create_promo')]]
    
    if promos:
        for promo in promos[:5]:  # Показываем кнопки удаления для первых 5
            code = promo[0]
            keyboard.append([InlineKeyboardButton(f"🗑 Удалить {code}", callback_data=f'admin_delete_promo_{code}')])
    
    keyboard.append([InlineKeyboardButton("◀️ Админ-панель", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def start_create_promocode(query, context):
    """Начать создание промокода"""
    text = "➕ СОЗДАНИЕ ПРОМОКОДА\n\n"
    text += "Отправьте промокод в формате:\n"
    text += "`КОД СУММА КОЛИЧЕСТВО`\n\n"
    text += "Например:\n"
    text += "`BONUS2024 5000 100`\n\n"
    text += "Где:\n"
    text += "• КОД - название промокода\n"
    text += "• СУММА - количество коинов\n"
    text += "• КОЛИЧЕСТВО - макс. использований"
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data='admin_promocodes')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    context.user_data['waiting_for_promo'] = True

async def delete_promocode(query, code):
    """Удалить промокод"""
    if db.delete_promocode(code):
        await query.answer(f"✅ Промокод {code} удален!", show_alert=True)
    else:
        await query.answer(f"❌ Ошибка удаления!", show_alert=True)
    
    await show_admin_promocodes(query)

async def start_broadcast(query, context):
    """Начать процесс рассылки"""
    text = "📢 РАССЫЛКА СООБЩЕНИЯ\n\n"
    text += "Напишите сообщение для рассылки всем пользователям.\n\n"
    text += "⚠️ Сообщение будет отправлено ВСЕМ!\n\n"
    text += "Чтобы отменить, напишите /cancel"
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data='admin_panel')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)
    
    context.user_data['waiting_for_broadcast'] = True

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Проверка промокода
    if not context.user_data.get('waiting_for_promo') and not context.user_data.get('waiting_for_broadcast'):
        # Попытка активировать промокод
        amount, message = db.use_promocode(user_id, text)
        
        if amount:
            await update.message.reply_text(
                f"✅ {message}!\n\n"
                f"💰 Вы получили: {amount:,} коинов\n"
                f"💵 Новый баланс: {db.get_user(user_id)[2]:,} коинов"
            )
        else:
            await update.message.reply_text(f"❌ {message}")
        return
    
    # Создание промокода (админ)
    if is_admin(user_id) and context.user_data.get('waiting_for_promo'):
        context.user_data['waiting_for_promo'] = False
        
        try:
            parts = text.split()
            if len(parts) != 3:
                raise ValueError()
            
            code, amount, max_uses = parts
            amount = int(amount)
            max_uses = int(max_uses)
            
            if db.create_promocode(code, amount, max_uses):
                await update.message.reply_text(
                    f"✅ Промокод создан!\n\n"
                    f"📌 Код: {code.upper()}\n"
                    f"💰 Сумма: {amount:,}\n"
                    f"👥 Использований: {max_uses}"
                )
            else:
                await update.message.reply_text("❌ Промокод уже существует!")
        except:
            await update.message.reply_text(
                "❌ Неверный формат!\n\n"
                "Используйте: `КОД СУММА КОЛИЧЕСТВО`",
                parse_mode='Markdown'
            )
        return
    
    # Рассылка (админ)
    if is_admin(user_id) and context.user_data.get('waiting_for_broadcast'):
        context.user_data['waiting_for_broadcast'] = False
        
        broadcast_text = text
        all_users = db.get_all_users()
        
        success_count = 0
        failed_count = 0
        
        status_message = await update.message.reply_text(
            f"📤 Начинаю рассылку...\n"
            f"Всего пользователей: {len(all_users)}"
        )
        
        for user_id_target in all_users:
            try:
                await context.bot.send_message(
                    chat_id=user_id_target,
                    text=f"📢 УВЕДОМЛЕНИЕ ОТ АДМИНИСТРАЦИИ\n\n{broadcast_text}"
                )
                success_count += 1
            except Exception as e:
                failed_count += 1
                logging.error(f"Ошибка рассылки для {user_id_target}: {e}")
        
        result_text = f"✅ Рассылка завершена!\n\n"
        result_text += f"📨 Отправлено: {success_count}\n"
        result_text += f"❌ Не доставлено: {failed_count}\n"
        result_text += f"👥 Всего: {len(all_users)}"
        
        await status_message.edit_text(result_text)

def main():
    """Запуск бота"""
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ ОШИБКА: Не указан токен бота!")
        print("📝 Откройте файл и замените YOUR_BOT_TOKEN_HERE на токен от @BotFather")
        return
    
    if ADMIN_ID == 123456789:
        print("⚠️  ВНИМАНИЕ: Не указан ID администратора!")
        print("📝 Замените 123456789 на ваш Telegram ID (узнать: @userinfobot)")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    print("=" * 50)
    print("🚀 Казино Бот v3.0 запущен!")
    print("📝 Пример работы от @kx_de")
    print("=" * 50)
    print(f"💾 База данных: casino_bot.db")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print("")
    print("🎮 Игры:")
    print("  🎰 Мины - выбирай клетки, избегай мин")
    print("  🚀 Ракета - лети высоко, забирай выигрыш")
    print("")
    print("⚙️  Админ-панель:")
    print("  📢 Рассылка сообщений")
    print("  📊 Статистика бота")
    print("  🎁 Создание промокодов")
    print("=" * 50)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

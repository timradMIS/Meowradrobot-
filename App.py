import asyncio
import threading
import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pyrogram import Client
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ========== توکن ربات ==========
BOT_TOKEN = "8889802048:AAG6lWBLvj-nAnWrrwjSMzip89WZEXFzSnY"

# ========== راه‌اندازی Flask ==========
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "🚀 ربات در حال اجراست!"

@app_flask.route('/health')
def health():
    return jsonify({"status": "running", "time": datetime.now().isoformat()}), 200

# ========== پایگاه داده ==========
Base = declarative_base()
engine = create_engine('sqlite:///users.db', echo=False)
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    api_id = Column(Integer, nullable=True)
    api_hash = Column(String, nullable=True)
    session_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)

class GroupSetting(Base):
    __tablename__ = 'group_settings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    chat_id = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

Base.metadata.create_all(engine)

# ========== مدیریت کاربران ==========
class UserManager:
    def __init__(self):
        self.active_users = {}
        self.sessions_dir = "sessions"
        os.makedirs(self.sessions_dir, exist_ok=True)
    
    async def create_user_session(self, telegram_id, username, api_id, api_hash):
        session = Session()
        try:
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    api_id=api_id,
                    api_hash=api_hash,
                    session_name=f"user_{telegram_id}"
                )
                session.add(user)
                session.commit()
            
            session_path = os.path.join(self.sessions_dir, f"user_{telegram_id}")
            client = Client(
                session_path,
                api_id=api_id,
                api_hash=api_hash,
                workdir=self.sessions_dir
            )
            
            await client.start()
            user.is_active = True
            user.last_active = datetime.utcnow()
            session.commit()
            
            self.active_users[telegram_id] = {
                'client': client,
                'settings': await self.load_user_settings(telegram_id)
            }
            
            return True, "✅ اتصال با موفقیت برقرار شد!"
        except Exception as e:
            return False, f"❌ خطا در اتصال: {str(e)}"
        finally:
            session.close()
    
    async def load_user_settings(self, telegram_id):
        session = Session()
        try:
            settings = session.query(GroupSetting).filter_by(user_id=telegram_id).all()
            return {setting.chat_id: setting.is_active for setting in settings}
        finally:
            session.close()
    
    async def toggle_group(self, telegram_id, chat_id, is_active):
        session = Session()
        try:
            setting = session.query(GroupSetting).filter_by(
                user_id=telegram_id,
                chat_id=str(chat_id)
            ).first()
            
            if not setting:
                setting = GroupSetting(
                    user_id=telegram_id,
                    chat_id=str(chat_id),
                    is_active=is_active
                )
                session.add(setting)
            else:
                setting.is_active = is_active
            
            session.commit()
            
            if telegram_id in self.active_users:
                self.active_users[telegram_id]['settings'][str(chat_id)] = is_active
            
            return True
        except Exception as e:
            print(f"خطا: {e}")
            return False
        finally:
            session.close()
    
    async def send_scheduled_message(self, telegram_id, chat_id, message):
        if telegram_id not in self.active_users:
            return False
        
        user_data = self.active_users[telegram_id]
        if not user_data['settings'].get(str(chat_id), False):
            return False
        
        try:
            client = user_data['client']
            await client.send_message(chat_id, message)
            return True
        except Exception as e:
            print(f"خطا در ارسال: {e}")
            return False
    
    async def stop_user_session(self, telegram_id):
        if telegram_id in self.active_users:
            try:
                await self.active_users[telegram_id]['client'].stop()
            except:
                pass
            del self.active_users[telegram_id]
            
            session = Session()
            try:
                user = session.query(User).filter_by(telegram_id=telegram_id).first()
                if user:
                    user.is_active = False
                    session.commit()
            finally:
                session.close()

# ========== دکمه‌ها ==========
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚀 شروع سرویس", callback_data="start_service")],
        [InlineKeyboardButton("🔧 مدیریت گروه‌ها", callback_data="manage_groups")],
        [InlineKeyboardButton("📊 وضعیت", callback_data="status")],
        [InlineKeyboardButton("⏹ توقف سرویس", callback_data="stop_service")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== راه‌اندازی ==========
user_manager = UserManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 **به ربات زمان‌بندی خوش آمدید!**\n\n"
        "این ربات به شما امکان می‌دهد سرویس ارسال خودکار 'مع' را روی اکانت خود فعال کنید.\n\n"
        "📌 برای دریافت API_ID و API_HASH به سایت my.telegram.org بروید.\n"
        "سپس روی دکمه 'شروع سرویس' کلیک کنید.",
        reply_markup=get_main_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "start_service":
        await query.edit_message_text(
            "🔑 **لطفاً اطلاعات زیر را وارد کنید:**\n\n"
            "1️⃣ ابتدا `API_ID` خود را وارد کنید (یک عدد).\n"
            "2️⃣ سپس `API_HASH` را وارد کنید (یک رشته).\n\n"
            "مثال:\n"
            "`123456` (API_ID)\n"
            "`abc123def456...` (API_HASH)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
            ])
        )
        context.user_data['waiting_for'] = 'api_id'
        
    elif query.data == "manage_groups":
        settings = await user_manager.load_user_settings(user_id)
        if not settings:
            await query.edit_message_text(
                "❌ شما هیچ گروهی را تنظیم نکرده‌اید.\n"
                "ابتدا سرویس را شروع کنید.",
                reply_markup=get_main_keyboard()
            )
            return
        
        text = "📋 **گروه‌های شما:**\n\n"
        keyboard = []
        for chat_id, is_active in settings.items():
            status = "✅ فعال" if is_active else "❌ غیرفعال"
            keyboard.append([
                InlineKeyboardButton(
                    f"{chat_id[:10]}... - {status}",
                    callback_data=f"toggle_{chat_id}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back")])
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif query.data.startswith("toggle_"):
        chat_id = query.data.replace("toggle_", "")
        current_settings = await user_manager.load_user_settings(user_id)
        current_status = current_settings.get(chat_id, False)
        new_status = not current_status
        
        await user_manager.toggle_group(user_id, chat_id, new_status)
        status_text = "فعال" if new_status else "غیرفعال"
        await query.edit_message_text(
            f"✅ وضعیت گروه به '{status_text}' تغییر کرد.",
            reply_markup=get_main_keyboard()
        )
        
    elif query.data == "status":
        user_data = user_manager.active_users.get(user_id)
        if user_data and user_data.get('client'):
            text = "✅ **سرویس فعال است**\n\n"
            text += f"📊 تعداد گروه‌ها: {len(user_data['settings'])}\n"
            active_groups = sum(1 for v in user_data['settings'].values() if v)
            text += f"✅ گروه‌های فعال: {active_groups}\n"
            text += f"❌ گروه‌های غیرفعال: {len(user_data['settings']) - active_groups}"
        else:
            text = "❌ **سرویس غیرفعال است**\n\nبرای شروع روی دکمه 'شروع سرویس' کلیک کنید."
        await query.edit_message_text(text, reply_markup=get_main_keyboard())
        
    elif query.data == "stop_service":
        await user_manager.stop_user_session(user_id)
        await query.edit_message_text(
            "⏹ **سرویس متوقف شد**\n"
            "برای شروع مجدد از دکمه شروع استفاده کنید.",
            reply_markup=get_main_keyboard()
        )
        
    elif query.data == "back":
        await query.edit_message_text(
            "🔙 به منوی اصلی بازگشتید",
            reply_markup=get_main_keyboard()
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if 'waiting_for' not in context.user_data:
        return
    
    state = context.user_data['waiting_for']
    
    if state == 'api_id':
        try:
            api_id = int(text)
            context.user_data['api_id'] = api_id
            context.user_data['waiting_for'] = 'api_hash'
            await update.message.reply_text(
                "✅ API_ID ذخیره شد!\n"
                "حالا لطفاً `API_HASH` خود را وارد کنید:"
            )
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید!")
            
    elif state == 'api_hash':
        api_hash = text
        context.user_data['api_hash'] = api_hash
        context.user_data['waiting_for'] = None
        
        status_msg = await update.message.reply_text("🔄 در حال اتصال به اکانت شما...")
        
        success, message = await user_manager.create_user_session(
            user_id,
            update.effective_user.username or "کاربر",
            context.user_data['api_id'],
            api_hash
        )
        
        await status_msg.edit_text(message)
        if success:
            await update.message.reply_text(
                "🎉 **سرویس با موفقیت راه‌اندازی شد!**\n\n"
                "ربات هر ۵ دقیقه و ۲ ثانیه پیام 'مع' را برای گروه‌های فعال شما ارسال می‌کند.\n"
                "برای مدیریت گروه‌ها از منو استفاده کنید.",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ اتصال ناموفق بود. دوباره تلاش کنید.",
                reply_markup=get_main_keyboard()
            )

async def scheduled_job(context: ContextTypes.DEFAULT_TYPE):
    """ارسال خودکار به تمام کاربران فعال"""
    for user_id, user_data in list(user_manager.active_users.items()):
        for chat_id, is_active in user_data['settings'].items():
            if is_active:
                try:
                    await user_manager.send_scheduled_message(
                        user_id,
                        int(chat_id),
                        "مع"
                    )
                except Exception as e:
                    print(f"خطا برای کاربر {user_id} در گروه {chat_id}: {e}")

async def error_handler(update, context):
    print(f"خطا: {context.error}")

# ========== اجرای ربات ==========
def run_bot():
    """اجرای ربات در یک ترد جداگانه"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_error_handler(error_handler)
    
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(scheduled_job, interval=302, first=10)
    
    print("🚀 ربات با موفقیت راه‌اندازی شد!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# ========== اجرای Flask و ربات ==========
if __name__ == "__main__":
    # اجرای ربات در ترد جداگانه
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # اجرای Flask
    port = int(os.environ.get("PORT", 5000))
    app_flask.run(host="0.0.0.0", port=port)

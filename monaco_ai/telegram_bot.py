from __future__ import annotations

import asyncio
import random
import re
import threading
import time

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from .commands import CommandContext, CommandRouter
from .config import Settings
from .utils import split_telegram
from .personality import load_personality, PersonalityProfile
from .telegram_settings import (
    TelegramRuntimeConfig,
    apply_telegram_runtime_config,
    load_telegram_runtime_config,
    mask_token,
    normalize_telegram_username,
    save_telegram_runtime_config,
)


class MonacoTelegramBot:
    def __init__(self, settings: Settings, router: CommandRouter):
        self.settings = settings
        self.router = router

    def allowed(self, update: Update) -> bool:
        if self.settings.telegram_allow_all:
            return True
        user = update.effective_user
        if not user:
            return False
        allowed_usernames = {normalize_telegram_username(u) for u in getattr(self.settings, "telegram_owner_usernames", set()) if normalize_telegram_username(u)}
        username = normalize_telegram_username(getattr(user, "username", ""))
        if username and username in allowed_usernames:
            return True
        # Backward compatibility: keep numeric IDs working if older configs still
        # have them, but the GUI now encourages usernames as the primary owner rule.
        return user.id in getattr(self.settings, "telegram_owner_ids", set())

    def _is_low_value_message(self, text: str, strictness: float) -> bool:
        clean = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not clean:
            return True
        low_words = {"lol", "lmao", "haha", "hahaha", "😂", "🤣", "ok", "oke", "ja", "nee", "yo", "hoi", "hey", "test", "?", "??"}
        if clean in low_words:
            return strictness >= 3.0
        if len(clean) <= 3:
            return strictness >= 4.0
        if len(clean.split()) == 1 and strictness >= 7.0:
            return True
        return False

    def _roll_reply(self, chance_0_to_10: float) -> bool:
        chance = max(0.0, min(10.0, float(chance_0_to_10))) / 10.0
        return random.random() <= chance

    def _should_reply(self, profile: PersonalityProfile, text: str, is_group: bool, is_command: bool, mentioned: bool, reply_to_bot: bool) -> bool:
        """Apply the Personality → Reply Rules to Telegram.

        Commands always work. Mentions/replies can override quiet mode. Normal
        group chatter is controlled by Telegram Group Replies + Silence/Low-value
        sliders so the bot can be quiet unless called.
        """
        if is_command:
            return True
        toggles = profile.toggles
        sliders = profile.sliders

        if is_group and not toggles.get("respond_in_groups", True):
            return False
        if not is_group and not toggles.get("respond_to_telegram_dm", True):
            return False

        if mentioned and toggles.get("answer_when_mentioned", True):
            return self._roll_reply(max(sliders.get("mention_priority", 10.0), sliders.get("response_frequency", 8.0)))
        if reply_to_bot and toggles.get("answer_replies_to_bot", True):
            return self._roll_reply(max(sliders.get("mention_priority", 10.0), sliders.get("response_frequency", 8.0)))

        if is_group and toggles.get("require_mention_in_groups", False):
            return False

        low_value_filter = sliders.get("low_value_filter", 5.0)
        if toggles.get("ignore_low_value_chatter", True) and self._is_low_value_message(text, low_value_filter):
            return False

        global_frequency = sliders.get("response_frequency", 8.0)
        if is_group:
            base = min(global_frequency, sliders.get("telegram_group_reply_frequency", 2.5))
            # A high silence threshold makes the bot less likely to join group chatter.
            base -= max(0.0, sliders.get("silence_threshold", 4.0) - 5.0) * 0.45
            base += max(0.0, sliders.get("interruptiveness", 2.0) - 5.0) * 0.35
            return self._roll_reply(base)
        base = min(global_frequency, sliders.get("telegram_dm_reply_frequency", 9.5))
        return self._roll_reply(base)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.allowed(update):
            await update.effective_message.reply_text("Geen toegang.")
            return
        msg = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        text = msg.text or msg.caption or ""
        if not text:
            await msg.reply_text("Ik kan nu vooral tekstberichten verwerken.")
            return

        profile = load_personality(self.settings)
        chat_type = getattr(chat, "type", "private") if chat else "private"
        is_group = chat_type in {"group", "supergroup"}
        is_command = text.strip().startswith("/")
        mentioned = False
        reply_to_bot = False
        try:
            me = await context.bot.get_me()
            bot_username = (me.username or "").lower()
            mentioned = bool(bot_username and f"@{bot_username}" in text.lower())
            if msg.reply_to_message and msg.reply_to_message.from_user:
                reply_to_bot = msg.reply_to_message.from_user.id == me.id
        except Exception:
            mentioned = False
            reply_to_bot = False

        if not self._should_reply(profile, text, is_group, is_command, mentioned, reply_to_bot):
            try:
                self.router.log_activity("Telegram message skipped by Personality reply rules.", "INFO")
            except Exception:
                pass
            return

        ctx = CommandContext(
            platform="telegram",
            chat_id=str(chat.id) if chat else "telegram_unknown",
            user_key=f"telegram:{user.id}" if user else None,
            username=user.username if user else None,
            display_name=(user.full_name if user else None),
        )
        out = await asyncio.to_thread(self.router.handle, text, ctx)
        await self._reply_long_text(msg, out)

    async def _reply_long_text(self, msg, text: str) -> None:
        """Send long Telegram replies safely in multiple messages.

        Telegram rejects messages above roughly 4096 chars. This method uses
        the robust splitter from utils.py, adds part numbers, and has a hard
        fallback so a giant single line can never make the bot fail silently.
        """
        profile = load_personality(self.settings)
        split_enabled = profile.toggles.get("split_long_telegram_messages", True)
        part_numbers = profile.toggles.get("number_split_telegram_messages", True)

        parts = split_telegram(text, max_len=3800, add_part_numbers=part_numbers) if split_enabled else [text or ""]
        for part in parts:
            if not part:
                continue
            try:
                await msg.reply_text(part)
            except Exception as exc:
                # Last-resort fallback: if Telegram still rejects something,
                # hard-split below 3000 chars and keep going instead of losing
                # the whole answer.
                try:
                    self.router.log_activity(f"Telegram send fallback activated: {type(exc).__name__}: {exc}", "WARN")
                except Exception:
                    pass
                for fallback in split_telegram(part, max_len=2900, add_part_numbers=False):
                    if fallback:
                        await msg.reply_text(fallback[:2900])

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("M0N4C0-AI online ✅ Stuur /help voor commands.")

    def build_application(self, token: str | None = None) -> Application:
        token = (token or self.settings.telegram_bot_token or "").strip()
        if not token:
            raise RuntimeError("Telegram bot token ontbreekt. Zet hem in de GUI Telegram pagina of .env.")
        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start", self.start_cmd))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        # Also route slash commands as text except /start.
        app.add_handler(MessageHandler(filters.COMMAND, self.handle_message))
        return app

    def run(self) -> None:
        app = self.build_application(self.settings.telegram_bot_token)
        print("Telegram bot gestart. Ctrl+C om te stoppen.")
        app.run_polling(close_loop=False)


class TelegramRuntimeController:
    """Start/stop Telegram polling live from the GUI without restarting M0N4C0."""

    def __init__(self, settings: Settings, router: CommandRouter):
        self.settings = settings
        self.router = router
        self.config = load_telegram_runtime_config(settings)
        apply_telegram_runtime_config(settings, self.config)
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._app: Application | None = None
        self._running = False
        self._last_error = ""
        self._started_at: float | None = None
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        return bool(self._running and self._thread and self._thread.is_alive())

    def start(self, cfg: TelegramRuntimeConfig | None = None) -> tuple[bool, str]:
        with self._lock:
            if cfg is not None:
                self.config = cfg
                apply_telegram_runtime_config(self.settings, cfg)
                save_telegram_runtime_config(self.settings, cfg)
            else:
                self.config = load_telegram_runtime_config(self.settings)
                apply_telegram_runtime_config(self.settings, self.config)
            if self.running:
                return True, "Telegram draait al live."
            token = (self.config.token or self.settings.telegram_bot_token or "").strip()
            if not token:
                return False, "Geen Telegram token ingesteld. Vul eerst Bot Token in en klik Save & Apply."
            self._stop_requested.clear()
            self._last_error = ""
            self._thread = threading.Thread(target=self._thread_main, args=(token,), daemon=True, name="M0N4C0TelegramRuntime")
            self._thread.start()
            return True, f"Telegram start live met token {mask_token(token)}."

    def stop(self, wait: bool = True) -> tuple[bool, str]:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                self._running = False
                return True, "Telegram stond al uit."
            self._stop_requested.set()
            thread = self._thread
        if wait:
            thread.join(timeout=12)
        with self._lock:
            if thread.is_alive():
                return False, "Stop-verzoek gestuurd, maar Telegram sluit nog af."
            self._running = False
            self._app = None
            return True, "Telegram is gestopt."

    def restart(self, cfg: TelegramRuntimeConfig | None = None) -> tuple[bool, str]:
        ok_stop, msg_stop = self.stop(wait=True)
        ok_start, msg_start = self.start(cfg)
        return ok_stop and ok_start, f"{msg_stop}\n{msg_start}"

    def _thread_main(self, token: str) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async(token))
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._running = False
            try:
                self.router.log_activity(f"Telegram runtime error: {self._last_error}", "ERR")
            except Exception:
                pass
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _run_async(self, token: str) -> None:
        bot = MonacoTelegramBot(self.settings, self.router)
        app = bot.build_application(token)
        self._app = app
        await app.initialize()
        await app.start()
        if app.updater is None:
            raise RuntimeError("python-telegram-bot updater is niet beschikbaar voor polling.")
        await app.updater.start_polling(drop_pending_updates=True)
        self._running = True
        self._started_at = time.time()
        try:
            self.router.log_activity("Telegram polling live gestart vanuit GUI.", "OK")
        except Exception:
            pass
        try:
            while not self._stop_requested.is_set():
                await asyncio.sleep(0.35)
        finally:
            try:
                if app.updater is not None:
                    await app.updater.stop()
            finally:
                try:
                    await app.stop()
                finally:
                    await app.shutdown()
            self._running = False
            self._app = None
            try:
                self.router.log_activity("Telegram polling live gestopt.", "WARN")
            except Exception:
                pass

    def status(self) -> dict[str, object]:
        uptime = 0
        if self._started_at and self.running:
            uptime = int(time.time() - self._started_at)
        return {
            "running": self.running,
            "enabled": bool(self.config.enabled),
            "token": mask_token(self.config.token or self.settings.telegram_bot_token),
            "allow_all": bool(self.settings.telegram_allow_all),
            "owner_ids": sorted(self.settings.telegram_owner_ids),
            "owner_usernames": sorted(getattr(self.settings, "telegram_owner_usernames", set())),
            "auto_start": bool(getattr(self.settings, "telegram_auto_start", False)),
            "uptime_seconds": uptime,
            "last_error": self._last_error,
        }

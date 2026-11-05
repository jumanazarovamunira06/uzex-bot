"""
UZEX AI Hackathon — Telegram bot (aiogram 3.x). Strictly SQL-grounded: every number/text shown comes from uzex.db.

Run:  pip install "aiogram>=3.7"
      BOT_TOKEN=123:ABC UZEX_DB=uzex.db python bot.py
"""
import asyncio
import logging
import os
import re
import sqlite3
import time
import uuid
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

# ───────────────────────────── Config ─────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "9221735709:AAFh0QHRgvu7Fb7Y2wPGLN5SyHjI--xcmbU")
DB_PATH = os.getenv("UZEX_DB", "uzex.db")
STATE_DB = os.getenv("STATE_DB", "bot_state.db")  # tiny separate DB for user language (main DB stays read-only)
PAGE_SIZE = 4          # cards per page
MAX_ROWS = 100         # max rows fetched per search
MAX_QUERY_LEN = 200
CACHE_TTL = 600        # schema/regions cache, seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("uzex-bot")
router = Router()

# ───────────────────────────── Texts ─────────────────────────────
T = {
    "ru": {
        "welcome": "👋 Добро пожаловать в бот данных Узбекской республиканской товарно-сырьевой биржи (UZEX).\n"
                   "Я отвечаю строго по данным базы. Если данных нет — я так и скажу.\n\nОтправьте запрос или нажмите «Помощь».",
        "help": "Примеры запросов:\n• хлопок\n• пшеница Ташкент\n• мука от 100000 до 500000\n• 123456789 (номер контракта или ИНН)\n\n"
                "Команды:\n/region <регион>\n/price <мин> <макс>\n/deals <запрос> — сделки\n/broker <название или ИНН>\n"
                "/participant <название или ИНН>\n/rate [дата] — курс USD\n/stats — статистика базы\n/filters — выбрать источник, регионы и др. фильтры\n/lang — сменить язык",
        "b_search": "🔎 Поиск", "b_stats": "📊 Статистика", "b_help": "ℹ️ Помощь", "b_lang": "🌐 Язык",
        "ask_query": "Введите название товара, регион, диапазон цен, номер контракта или ИНН.",
        "u_auto": "Введите запрос: название товара, регион, диапазон цен (например: «мука от 100000 до 500000»).",
        "u_region": "Укажите регион, например: /region Самарканд пшеница",
        "u_price": "Укажите диапазон цен, например: /price 100000 500000 или /price хлопок до 2000000",
        "u_deals": "Укажите запрос, например: /deals хлопок",
        "u_broker": "Укажите название или ИНН брокера, например: /broker 123456789",
        "u_participant": "Укажите название или ИНН участника, например: /participant 123456789",
        "not_found": "❌ По запросу «{q}» в базе данных ничего не найдено.",
        "no_region": "❌ Такой регион в базе не найден. Регионы в базе:",
        "no_table": "❌ Таблица «{t}» отсутствует в базе данных.",
        "db_error": "⚠️ Временная ошибка доступа к базе данных. Повторите попытку через несколько секунд.",
        "too_long": "⚠️ Запрос слишком длинный (максимум {n} символов).",
        "unsupported": "Пожалуйста, отправьте текстовый запрос.",
        "expired": "Результаты устарели, повторите поиск.",
        "found": "🔎 Найдено записей", "source": "Источник", "shown": "Показано", "of": "из",
        "capped": "Доступны первые {n} записей — уточните запрос.",
        "rate_last": "Последние записи в таблице (в порядке хранения в базе).",
        "stats_title": "📊 Статистика базы", "regions_cnt": "Регионов в контрактах", "products_cnt": "Уникальных продуктов",
        "lang_saved": "✅ Язык: Русский", "unknown_cmd": "Неизвестная команда. См. /help",
        "b_filters": "⚙️ Фильтры", "f_title": "⚙️ Фильтры поиска", "f_source": "Источник данных",
        "f_hint": "Фильтры (регион, год, состояние сделки, тип торгов и др.) применяются к контрактам и сделкам там, где есть такое поле, и действуют на все следующие запросы. "
                  "Можно выбрать несколько значений.",
        "f_pick": "Выберите значения (можно несколько):", "f_clear": "🧹 Сбросить", "f_clear_all": "🧹 Сбросить всё",
        "f_done": "✔️ Готово", "f_back": "⬅️ Назад", "f_none": "не выбрано", "f_active": "Активные фильтры",
        "f_pick_src": "Выберите, где искать:",
        "sum_title": "📊 Итого по всей выборке", "sum_deals": "сделок", "sum_amount": "сумма (без аннулированных)",
        "sum_volume": "объём", "sum_avg": "ср. цена за ед.", "sum_states": "По состоянию",
        "deal_price_note": "Диапазон цен применён к сумме сделки.",
    },
    "uz": {
        "welcome": "👋 O'zbekiston Respublika tovar-xom ashyo birjasi (UZEX) ma'lumotlari botiga xush kelibsiz.\n"
                   "Men faqat bazadagi ma'lumotlarga tayanaman. Ma'lumot bo'lmasa — shuni aytaman.\n\nSo'rov yuboring yoki «Yordam» tugmasini bosing.",
        "help": "So'rov namunalari:\n• paxta\n• bug'doy Toshkent\n• un 100000 dan 500000 gacha\n• 123456789 (shartnoma raqami yoki STIR)\n\n"
                "Buyruqlar:\n/region <hudud>\n/price <min> <max>\n/deals <so'rov> — bitimlar\n/broker <nomi yoki STIR>\n"
                "/participant <nomi yoki STIR>\n/rate [sana] — USD kursi\n/stats — baza statistikasi\n/filters — manba, hududlar va boshqa filtrlar\n/lang — tilni o'zgartirish",
        "b_search": "🔎 Qidiruv", "b_stats": "📊 Statistika", "b_help": "ℹ️ Yordam", "b_lang": "🌐 Til",
        "ask_query": "Mahsulot nomi, hudud, narx oralig'i, shartnoma raqami yoki STIR kiriting.",
        "u_auto": "So'rov kiriting: mahsulot nomi, hudud, narx oralig'i (masalan: «un 100000 dan 500000 gacha»).",
        "u_region": "Hududni kiriting, masalan: /region Samarqand bug'doy",
        "u_price": "Narx oralig'ini kiriting, masalan: /price 100000 500000 yoki /price paxta 2000000 gacha",
        "u_deals": "So'rovni kiriting, masalan: /deals paxta",
        "u_broker": "Broker nomi yoki STIR kiriting, masalan: /broker 123456789",
        "u_participant": "Ishtirokchi nomi yoki STIR kiriting, masalan: /participant 123456789",
        "not_found": "❌ «{q}» so'rovi bo'yicha ma'lumotlar bazasida hech narsa topilmadi.",
        "no_region": "❌ Bunday hudud bazada topilmadi. Bazadagi hududlar:",
        "no_table": "❌ «{t}» jadvali ma'lumotlar bazasida mavjud emas.",
        "db_error": "⚠️ Ma'lumotlar bazasiga kirishda vaqtinchalik xatolik. Bir necha soniyadan keyin qayta urinib ko'ring.",
        "too_long": "⚠️ So'rov juda uzun (maksimum {n} belgi).",
        "unsupported": "Iltimos, matnli so'rov yuboring.",
        "expired": "Natijalar eskirgan, qidiruvni qaytaring.",
        "found": "🔎 Topilgan yozuvlar", "source": "Manba", "shown": "Ko'rsatilgan", "of": "dan",
        "capped": "Dastlabki {n} ta yozuv mavjud — so'rovni aniqlashtiring.",
        "rate_last": "Jadvaldagi oxirgi yozuvlar (bazada saqlanish tartibida).",
        "stats_title": "📊 Baza statistikasi", "regions_cnt": "Shartnomalardagi hududlar", "products_cnt": "Noyob mahsulotlar",
        "lang_saved": "✅ Til: O'zbek tili", "unknown_cmd": "Noma'lum buyruq. /help ni ko'ring",
        "b_filters": "⚙️ Filtrlar", "f_title": "⚙️ Qidiruv filtrlari", "f_source": "Ma'lumot manbai",
        "f_hint": "Filtrlar (hudud, yil, bitim holati, savdo turi va b.) shartnoma va bitimlarga (maydon mavjud bo'lsa) qo'llanadi va keyingi barcha so'rovlarda amal qiladi. "
                  "Bir nechta qiymat tanlash mumkin.",
        "f_pick": "Qiymatlarni tanlang (bir nechta mumkin):", "f_clear": "🧹 Tozalash", "f_clear_all": "🧹 Hammasini tozalash",
        "f_done": "✔️ Tayyor", "f_back": "⬅️ Orqaga", "f_none": "tanlanmagan", "f_active": "Faol filtrlar",
        "f_pick_src": "Qayerdan qidirishni tanlang:",
        "sum_title": "📊 Butun tanlanma bo'yicha jami", "sum_deals": "bitim", "sum_amount": "summa (bekor qilinganlarsiz)",
        "sum_volume": "hajm", "sum_avg": "birlik o'rtacha narxi", "sum_states": "Holatlar bo'yicha",
        "deal_price_note": "Narx oralig'i bitim summasiga qo'llandi.",
    },
}
CHOOSE_LANG = "🌐 Tilni tanlang / Выберите язык"

# Contract fields: key -> DB column name
C = dict(no="Номер контракта", name="Наименование продукта", brand="Марка товара", size="Размер товара",
         grade="Сорт товара", type="Тип товара", cls="Класс товара", hs="Код ТН ВЭД", group="Группа товара",
         cat="Категория товара", ind="Отрасль промышленности", unit="Единица измерения", lot="Лот",
         cur="Валюта", price="Базисная цена", dep="Сумма залога", basis="Базис поставки", region="Регион",
         addr="Адрес склада", trade="Тип торгов", ctype="Тип контракта", form="Форма контракта",
         pay="Срок оплаты", deliv="Срок поставки", pack="Упаковка", inn="ИНН продавца",
         reg="Дата регистрации", valid="Действует до")
LBL = {
    "ru": dict(no="Контракт №", brand="Марка", grade="Сорт", size="Размер", type="Тип", cls="Класс", pack="Упаковка",
               price="Базисная цена", lot="Лот", dep="Сумма залога", region="Регион", basis="Базис поставки",
               addr="Склад", deliv="Срок поставки", pay="Срок оплаты", trade="Тип торгов", ctype="Тип контракта",
               form="Форма", group="Группа", cat="Категория", ind="Отрасль", hs="Код ТН ВЭД", reg="Регистрация",
               valid="Действует до", inn="ИНН продавца",
               deal_no="Сделка №", qty="Количество", amount="Сумма сделки", uprice="Цена за ед.", sprice="Стартовая цена",
               state="Состояние", seller="Продавец", buyer="Покупатель", brokers="Брокеры", paid="Оплата",
               dlv="Поставка", dlvd="Поставлено лотов"),
    "uz": dict(no="Shartnoma №", brand="Marka", grade="Navi", size="O'lcham", type="Turi", cls="Sinf", pack="Qadoqlash",
               price="Bazaviy narx", lot="Lot", dep="Garov summasi", region="Hudud", basis="Yetkazib berish bazisi",
               addr="Ombor", deliv="Yetkazib berish muddati", pay="To'lov muddati", trade="Savdo turi",
               ctype="Shartnoma turi", form="Shakli", group="Guruh", cat="Kategoriya", ind="Tarmoq", hs="TN VED kodi",
               reg="Ro'yxatdan o'tgan", valid="Amal qilish muddati", inn="Sotuvchi STIR",
               deal_no="Bitim №", qty="Miqdor", amount="Bitim summasi", uprice="Birlik narxi", sprice="Boshlang'ich narx",
               state="Holati", seller="Sotuvchi", buyer="Xaridor", brokers="Brokerlar", paid="To'lov",
               dlv="Yetkazish", dlvd="Yetkazilgan lotlar"),
}
# Selectable filters: key -> (icon, RU label, UZ label); keys refer to contract columns in C
FIELDS = {"region": ("📍", "Регион", "Hudud"), "year": ("📆", "Год сделки", "Bitim yili"),
          "status": ("📌", "Состояние сделки", "Bitim holati"), "cat": ("🧱", "Категория товара", "Tovar kategoriyasi"),
          "trade": ("🏷", "Тип торгов", "Savdo turi"), "ctype": ("📑", "Тип контракта", "Shartnoma turi"),
          "form": ("📋", "Форма контракта", "Shartnoma shakli"), "group": ("🗂", "Группа товара", "Mahsulot guruhi"),
          "cur": ("💱", "Валюта", "Valyuta")}
# Selectable data sources ("documents"): key -> (RU, UZ)
SRC = {"auto": ("Все источники (авто)", "Barcha manbalar (avto)"), "contracts": ("Контракты", "Shartnomalar"),
       "deals": ("Сделки", "Bitimlar"), "participants": ("Участники", "Ishtirokchilar"),
       "brokers": ("Брокеры", "Brokerlar"), "rates": ("Курс USD", "USD kursi")}
PER_PICK = 10
SEARCH_KEYS = ("name", "brand", "type", "group", "cat", "ind", "no", "hs")  # contract columns searched by keywords

# ───────────────────── Text helpers (MarkdownV2) ─────────────────────
_MD = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def e(s) -> str:
    return _MD.sub(r"\\\1", str(s))


def b(s) -> str:
    return f"*{e(s)}*"


def code(s) -> str:
    return "`" + str(s).replace("\\", "\\\\").replace("`", "\\`") + "`"


def plain(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s).replace("*", "")


def clip(s: str, n: int = 90) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def clean(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("", "nan", "none", "null", "nat") else s


def to_num(x):
    """Parse numbers stored as text ('1 250 000,50') -> float or None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[^\d,.\-]", "", str(x))
    if not s or s in "-.,":
        return None
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
        s = s.replace(",", "")
    elif "," in s and "." in s:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def fmt_num(s: str) -> str:
    v = to_num(s)
    if v is None:
        return s
    return f"{int(v):,}".replace(",", " ") if v == int(v) else f"{v:,.2f}".replace(",", " ")


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ───────────────────── Query understanding ─────────────────────
STOP = set("""в на по и или для из с со от до цена цены цену цене контракт контракты контрактов товар товара регион
область области обл город г найти найди покажи показать скажи сколько стоит
shahri respublikasi республика yil yili yilda год года narx narxi va uchun bo'yicha shartnoma viloyat viloyati tuman shahar qidirish ko'rsat dan gacha
the in of price region contract show find from to""".split())

# Uzbek-latin / English -> Russian stems (DB values are Russian). Longest prefix wins.
ALIASES = {
    "paxta": "хлоп", "bugdoy": "пшениц", "bug'doy": "пшениц", "un": "мука", "shakar": "сахар", "neft": "нефт",
    "gaz": "газ", "benzin": "бензин", "dizel": "дизел", "mazut": "мазут", "ko'mir": "уголь", "sement": "цемент",
    "metall": "металл", "po'lat": "сталь", "armatura": "арматур", "mis": "медь", "alyuminiy": "алюмин",
    "kartoshka": "картоф", "piyoz": "лук", "guruch": "рис", "sabzi": "морков", "pomidor": "помидор",
    "o'g'it": "удобрен", "yog'": "масл", "yog'och": "древес", "go'sht": "мяс", "sut": "молок", "tuxum": "яйц",
    "makkajo'xori": "кукуруз", "arpa": "ячмен", "qog'oz": "бумаг", "shisha": "стекл", "plastik": "пластик",
    "polietilen": "полиэтилен", "karbamid": "карбамид", "ammiak": "аммиак",
    "toshkent": "ташкент", "tashkent": "ташкент", "samarqand": "самарканд", "buxoro": "бухар", "bukhara": "бухар",
    "farg'ona": "ферган", "fargona": "ферган", "fergana": "ферган", "andijon": "андижан", "namangan": "наманган",
    "qashqadaryo": "кашкадарь", "surxondaryo": "сурхандарь", "xorazm": "хорезм", "navoiy": "навои",
    "jizzax": "джизак", "sirdaryo": "сырдарь", "qoraqalpog'iston": "каракалпак", "qoraqalpogiston": "каракалпак",
}
_LAT = {"a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "ж", "k": "к", "l": "л",
        "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "х",
        "y": "й", "z": "з"}
_DI = [("o'", "о"), ("g'", "г"), ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ng", "нг")]


def translit(t: str) -> str:
    for a, c in _DI:
        t = t.replace(a, c)
    return "".join(_LAT.get(ch, ch) for ch in t)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[’‘ʻʼ`´]", "'", s.lower())).strip()


def variants(tok: str) -> set:
    """Search forms of a token: original, RU alias, transliteration, light stem."""
    v = {tok}
    hits = [k for k in ALIASES if tok == k or (len(k) >= 4 and tok.startswith(k))]
    if hits:
        v.add(ALIASES[max(hits, key=len)])
    if len(tok) >= 4 and re.search(r"[a-z]", tok):
        v.add(translit(tok))
    if tok.isalpha() and len(tok) >= 5:      # light stemming: нефть -> нефт, пшеницы -> пшениц
        v.add(tok[:-1])
    if tok.isalpha() and len(tok) >= 6:
        v.add(tok[:-2])
    return {x for x in v if x}


NUM = r"(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)"
_RANGE = re.compile(rf"(?:цена|narx|price)\s*{NUM}\s*[-–—]\s*{NUM}")
_PMIN = [re.compile(rf"(?<!\w)(?:от|from|min|>=|>)\s*{NUM}"), re.compile(rf"{NUM}\s*(?:dan|дан)(?!\w)")]
_PMAX = [re.compile(rf"(?<!\w)(?:до|to|max|<=|<)\s*{NUM}"), re.compile(rf"{NUM}\s*(?:gacha|гача)(?!\w)")]


def extract_price(s: str):
    pmin = pmax = None
    m = _RANGE.search(s)
    if m:
        pmin, pmax = to_num(m.group(1)), to_num(m.group(2))
        s = s[:m.start()] + " " + s[m.end():]
    for pat in _PMIN:
        m = pat.search(s)
        if m:
            pmin = to_num(m.group(1))
            s = s[:m.start()] + " " + s[m.end():]
    for pat in _PMAX:
        m = pat.search(s)
        if m:
            pmax = to_num(m.group(1))
            s = s[:m.start()] + " " + s[m.end():]
    if pmin is not None and pmax is not None and pmin > pmax:
        pmin, pmax = pmax, pmin
    return pmin, pmax, s


def tokens(s: str) -> list:
    out = []
    for t in re.findall(r"[\w'./\-]+", norm(s)):
        t = t.strip(".,-/'")
        if t and t not in STOP and (len(t) > 1 or t.isdigit()):
            out.append(t)
    return out[:8]


@dataclass
class Query:
    kws: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    pmin: float = None
    pmax: float = None

    @property
    def empty(self):
        return not (self.kws or self.regions or self.pmin is not None or self.pmax is not None)


def parse_query(text: str, regions_lc: list) -> Query:
    pmin, pmax, rest = extract_price(norm(text))
    q = Query(pmin=pmin, pmax=pmax)
    for t in tokens(rest):
        stem = None
        if not t.isdigit():
            for v in variants(t):
                if len(v) >= 5 and any(v[:6] in r for r in regions_lc):
                    stem = v[:6]
                    break
        (q.regions if stem else q.kws).append(stem or t)
    low = norm(text)
    city = re.search(r"shahri|shahar|город|(?<!\w)г\.", low)
    oblast = re.search(r"viloyat|област|(?<!\w)обл", low)
    q.regions = [("г. ташкент" if city else "ташкентск" if oblast else s_) if s_ == "ташкен" else s_ for s_ in q.regions]
    return q


# ───────────────────────────── Database ─────────────────────────────
def db_connect() -> sqlite3.Connection:
    uri = Path(DB_PATH).resolve().as_uri() + "?mode=ro"  # read-only: bot can never alter data
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.create_function("lc", 1, lambda x: "" if x is None else str(x).lower(), deterministic=True)
    conn.create_function("num", 1, to_num, deterministic=True)
    return conn


def query(conn, sql, params=()):
    """Execute with retries on 'database is locked'."""
    for i in range(3):
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as ex:
            if "locked" in str(ex).lower() or "busy" in str(ex).lower():
                time.sleep(0.4 * (i + 1))
                continue
            raise
    raise sqlite3.OperationalError("database is locked")


@dataclass
class Ctx:
    ts: float
    schema: dict
    roles: dict
    c: dict            # contract key -> real column name (or None)
    regions_lc: list
    vals: dict = field(default_factory=dict)   # lazily loaded filter values
    regions_raw: list = field(default_factory=list)
    states: list = field(default_factory=list)


_ctx: Ctx = None


def get_ctx(conn) -> Ctx:
    global _ctx
    if _ctx and time.time() - _ctx.ts < CACHE_TTL:
        return _ctx
    names = [r[0] for r in query(conn, "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")]
    schema = {n: [r[1] for r in query(conn, f"PRAGMA table_info({qi(n)})")] for n in names}

    def pick(*ks):
        return [t for t in names if any(k in t.lower() for k in ks)]
    part, brok = pick("particip", "участник"), pick("broker", "брокер")
    deals = [t for t in pick("deal", "сделк") if t not in part + brok]
    contracts = [t for t in names if t.lower() == "contracts"] or [t for t in pick("contract", "контракт") if t not in deals][:1]
    rates = [t for t in pick("usd", "rate", "курс") if t not in contracts + deals + part + brok]
    roles = dict(contracts=contracts, deals=deals, participants=part, brokers=brok, rates=rates)
    cmap, regions, regions_raw, states = {}, [], [], []
    if contracts:
        low = {c.lower(): c for c in schema[contracts[0]]}
        cmap = {k: low.get(v.lower()) for k, v in C.items()}
        if cmap.get("region"):
            regions_raw = [clean(r[0]) for r in query(conn, f"SELECT DISTINCT {qi(cmap['region'])} FROM {qi(contracts[0])}") if clean(r[0])]
            regions = [r.lower() for r in regions_raw]
    if deals and "Состояние сделки" in schema[deals[0]]:
        states = [clean(r[0]) for r in query(conn, f'SELECT DISTINCT "Состояние сделки" FROM {qi(deals[0])}') if clean(r[0])]
    _ctx = Ctx(time.time(), schema, roles, cmap, regions, regions_raw=regions_raw, states=states)
    return _ctx


# ───────────────────────────── Results & formatting ─────────────────────────────
@dataclass
class Result:
    status: str = "ok"      # ok | none | empty | no_region | no_price | no_table
    items: list = field(default_factory=list)
    total: int = 0
    source: str = ""
    note: str = ""
    q: str = ""
    flt_note: str = ""
    summary: str = ""


def contract_card(r: dict, ctx: Ctx, lang: str) -> str:
    L = LBL[lang]

    def g(k):
        col = ctx.c.get(k)
        return clip(clean(r.get(col))) if col else ""
    out = [f"📄 {b(L['no'])} {code(g('no') or '—')}"]
    if g("name"):
        out.append(f"📦 {b(g('name'))}")
    det = [f"{L[k]}: {g(k)}" for k in ("brand", "grade", "size", "type", "cls", "pack") if g(k)]
    if det:
        out.append("     " + e(" · ".join(det)))
    if g("price"):
        s = f"{fmt_num(g('price'))} {g('cur')}".strip() + (f" / {g('unit')}" if g("unit") else "")
        out.append(f"💰 {b(L['price'])}: {e(s)}")
    if g("lot"):
        out.append(f"⚖️ {e(L['lot'])}: {e(g('lot'))}")
    if g("dep"):
        out.append(f"🔒 {e(L['dep'])}: {e(g('dep'))}")
    if g("region"):
        out.append(f"📍 {b(L['region'])}: {e(g('region'))}")
    for k, ic in (("basis", "🏭"), ("addr", "🗺"), ("deliv", "🚚"), ("pay", "💳"), ("trade", "🏷"), ("ctype", "📑"),
                  ("form", "📋"), ("group", "🗂"), ("cat", "🗂"), ("ind", "🏗"), ("hs", "🔢"), ("reg", "📅"),
                  ("valid", "⏳"), ("inn", "🏢")):
        if g(k):
            out.append(f"{ic} {e(L[k])}: {e(g(k))}")
    return "\n".join(out)


HIDDEN = {"date_iso", "rate_num", "region_ru", "reg_iso", "valid_iso", "price_num", "name_lc", "year", "currency"}


def generic_card(r: dict, table: str) -> str:
    out = [f"🔹 {b(table)}"]
    n = 0
    for k, v in r.items():
        v = clean(v)
        if v and n < 10 and k not in HIDDEN:
            out.append(f"• {b(k)}: {e(clip(v, 80))}")
            n += 1
    return "\n".join(out)


def search_contracts(conn, ctx: Ctx, q: Query, lang: str, text: str, flt: dict = None) -> Result:
    if not ctx.roles["contracts"]:
        return Result("no_table", source="contracts")
    t, c = ctx.roles["contracts"][0], ctx.c
    where, params = [], []
    scols = [c[k] for k in SEARCH_KEYS if c.get(k)]
    for kw in q.kws:
        parts = []
        cols = scols + ([c["inn"]] if kw.isdigit() and c.get("inn") else [])
        for col in cols:
            for v in variants(kw):
                parts.append(f"instr(lc({qi(col)}),?)>0")
                params.append(v)
        where.append("(" + " OR ".join(parts or ["0"]) + ")")
    for s in q.regions:
        where.append(f"instr(lc({qi(c['region'])}),?)>0")
        params.append(s)
    for fk, vals in (flt or {}).items():
        col = fcol(ctx, fk, "contracts")
        if col and vals:
            where.append(f"{qi(col)} IN ({','.join('?' * len(vals))})")
            params += list(vals)
    order = ""
    if (q.pmin is not None or q.pmax is not None) and c.get("price"):
        pc = f"num({qi(c['price'])})"
        if q.pmin is not None:
            where.append(f"{pc}>=?")
            params.append(q.pmin)
        if q.pmax is not None:
            where.append(f"{pc}<=?")
            params.append(q.pmax)
        order = f" ORDER BY {pc} ASC"
    w = " AND ".join(where) or "1"
    total = query(conn, f"SELECT COUNT(*) FROM {qi(t)} WHERE {w}", params)[0][0]
    if not total:
        return Result("none", q=text)
    rows = query(conn, f"SELECT * FROM {qi(t)} WHERE {w}{order} LIMIT {MAX_ROWS}", params)
    return Result("ok", [contract_card(dict(r), ctx, lang) for r in rows], total, t, q=text)


def search_generic(conn, ctx: Ctx, tables: list, kws: list, text: str) -> Result:
    items, total, used = [], 0, []
    for t in tables:
        cols, where, params = ctx.schema[t], [], []
        for kw in kws:
            parts = []
            for col in cols:
                for v in variants(kw):
                    parts.append(f"instr(lc({qi(col)}),?)>0")
                    params.append(v)
            where.append("(" + " OR ".join(parts) + ")")
        w = " AND ".join(where)
        n = query(conn, f"SELECT COUNT(*) FROM {qi(t)} WHERE {w}", params)[0][0]
        if not n:
            continue
        total += n
        used.append(t)
        room = MAX_ROWS - len(items)
        if room > 0:
            rows = query(conn, f"SELECT * FROM {qi(t)} WHERE {w} LIMIT {room}", params)
            items += [generic_card(dict(r), t) for r in rows]
    return Result("ok", items, total, ", ".join(used), q=text) if total else Result("none", q=text)


DEAL_HELPERS = {"name_lc", "currency", "region_ru", "amount_num", "date_iso", "year", "volume_units", "unit_price"}
DEAL_COLS = {"region": "region_ru", "trade": "Тип торгов", "ctype": "Тип контракта", "form": "Форма контракта",
             "cur": "currency", "status": "Состояние сделки", "year": "year"}


def deals_ready(ctx: Ctx) -> bool:
    """True when the single deals table has the helper columns created by build_db.py."""
    return len(ctx.roles["deals"]) == 1 and DEAL_HELPERS <= set(ctx.schema[ctx.roles["deals"][0]])


def fcol(ctx: Ctx, k: str, table: str):
    if table == "contracts":
        return ctx.c.get(k) if k in ("region", "trade", "ctype", "form", "group", "cat", "cur") else None
    return DEAL_COLS.get(k) if deals_ready(ctx) else None


def money(v) -> str:
    return "—" if v is None else f"{v:,.0f}".replace(",", " ")


def deal_card(r: dict, lang: str) -> str:
    L = LBL[lang]

    def g(k, n=90):
        return clip(clean(r.get(k)), n)
    out = [f"🤝 {b(L['deal_no'])} {code(g('Номер сделки'))} · {e(g('Дата сделки'))} {e(g('Время сделки'))}",
           f"📦 {b(g('Наименование товара', 120))}",
           f"📐 {e(L['qty'])}: {e(g('Количество'))} × {e(g('Лот'))} {e(g('Единица измерения'))}",
           f"💰 {b(L['amount'])}: {e(g('Сумма сделки'))} {e(g('currency'))}"]
    if r.get("unit_price") is not None:
        out.append(f"     {e(L['uprice'])}: {e(fmt_num(format(r['unit_price'], '.2f')))} / {e(g('Единица измерения'))}")
    if g("Стартовая цена"):
        out.append(f"     {e(L['sprice'])}: {e(g('Стартовая цена'))}")
    out.append(f"📌 {b(L['state'])}: {e(g('Состояние сделки'))}")
    out.append(f"📍 {e(g('region_ru') if lang == 'ru' else g('Регион'))}")
    out.append("🏷 " + e(" · ".join(x for x in (g("Тип торгов"), g("Тип контракта"), g("Форма контракта")) if x)))
    out.append(f"🏢 {e(L['seller'])}: {e(g('seller_name') or '—')} ({e(g('ИНН продавца'))})")
    out.append(f"🏢 {e(L['buyer'])}: {e(g('buyer_name') or '—')} ({e(g('ИНН покупателя'))})")
    out.append(f"🧾 {e(L['brokers'])}: {e(g('bs_name') or g('Брокер продавца'))} → {e(g('bb_name') or g('Брокер покупателя'))}")
    if g("Дата оплаты"):
        out.append(f"💳 {e(L['paid'])}: {e(g('Дата оплаты'))}")
    if g("Дата поставки"):
        out.append(f"🚚 {e(L['dlv'])}: {e(g('Дата поставки'))} · {e(L['dlvd'])}: {e(g('Поставлено'))}")
    out.append(f"📄 {e(L['no'])} {code(g('Номер контракта'))}")
    return "\n".join(out)


def search_deals(conn, ctx: Ctx, q: Query, text: str, lang: str, flt: dict = None) -> Result:
    """Structured deals search + aggregate summary (all numbers come from SQL over the full matched set)."""
    t = ctx.roles["deals"][0]
    where, params = [], []
    for kw in q.kws:
        st = [s_ for s_ in ctx.states if len(kw) >= 6 and s_.lower().startswith(kw[:6])]
        if re.fullmatch(r"20\d\d", kw):
            where.append("d.year=?"); params.append(kw)
        elif re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", kw):
            where.append("d.date_iso=?"); params.append(f"{kw[6:]}-{kw[3:5]}-{kw[:2]}")
        elif re.fullmatch(r"\d{9}", kw):
            where.append('(d."ИНН продавца"=? OR d."ИНН покупателя"=?)'); params += [kw, kw]
        elif re.fullmatch(r"\d{5,8}", kw):
            where.append('(d."Номер контракта"=? OR d."Номер сделки"=?)'); params += [kw, kw]
        elif re.fullmatch(r"bk\d+", kw):
            where.append('(d."Брокер продавца"=? OR d."Брокер покупателя"=?)'); params += [kw.upper()] * 2
        elif st:
            where.append(f'd."Состояние сделки" IN ({",".join("?" * len(st))})'); params += st
        else:
            vs = sorted(variants(kw))
            where.append("(" + " OR ".join("instr(d.name_lc,?)>0" for _ in vs) + ")"); params += vs
    for s_ in q.regions:
        names = [r for r in ctx.regions_raw if s_ in r.lower()]
        where.append(f"d.region_ru IN ({','.join('?' * len(names))})" if names else "0"); params += names
    price_note = q.pmin is not None or q.pmax is not None
    if q.pmin is not None:
        where.append("d.amount_num>=?"); params.append(q.pmin)
    if q.pmax is not None:
        where.append("d.amount_num<=?"); params.append(q.pmax)
    for fk, vals in (flt or {}).items():
        if not vals:
            continue
        ph = ",".join("?" * len(vals))
        if fcol(ctx, fk, "deals"):
            where.append(f"d.{qi(fcol(ctx, fk, 'deals'))} IN ({ph})"); params += list(vals)
        elif fcol(ctx, fk, "contracts") and ctx.roles["contracts"] and ctx.c.get("no"):   # contract-level field, e.g. category
            where.append(f'd."Номер контракта" IN (SELECT {qi(ctx.c["no"])} FROM {qi(ctx.roles["contracts"][0])} '
                         f'WHERE {qi(fcol(ctx, fk, "contracts"))} IN ({ph}))'); params += list(vals)
    if not where:
        return Result("empty")
    w = " AND ".join(where)
    ann = "d.\"Состояние сделки\" LIKE 'Аннулирован%'"
    agg = query(conn, f"SELECT d.currency AS cur, COUNT(*) AS n, SUM(CASE WHEN {ann} THEN 0 ELSE d.amount_num END) AS s, "
                      f"SUM(CASE WHEN {ann} THEN 0 ELSE d.volume_units END) AS v, COUNT(DISTINCT d.\"Единица измерения\") AS u, "
                      f"MIN(d.\"Единица измерения\") AS unit FROM {qi(t)} d WHERE {w} GROUP BY d.currency", params)
    total = sum(r["n"] for r in agg)
    if not total:
        return Result("none", q=text)
    tt = T[lang]
    lines = [b(tt["sum_title"])]
    for r in agg:
        line = f"• {e(r['cur'] or '?')}: {r['n']} {e(tt['sum_deals'])}; {e(tt['sum_amount'])}: {e(money(r['s']))}"
        if r["u"] == 1 and r["v"]:          # average price only when every deal uses the same unit of measure
            line += (f"; {e(tt['sum_volume'])}: {e(money(r['v']))} {e(r['unit'])}; "
                     f"{e(tt['sum_avg'])}: {e(fmt_num(format(r['s'] / r['v'], '.2f')))}")
        lines.append(line)
    sts = query(conn, f'SELECT d."Состояние сделки" AS st, COUNT(*) AS n FROM {qi(t)} d WHERE {w} GROUP BY 1 ORDER BY 2 DESC', params)
    lines.append(f"• {e(tt['sum_states'])}: " + e(" · ".join(f"{r['st']}: {r['n']}" for r in sts)))
    if price_note:
        lines.append(e(tt["deal_price_note"]))
    sql = (f'SELECT d.*, ps."Наименование" AS seller_name, pb."Наименование" AS buyer_name, '
           f'bs."Наименование" AS bs_name, bb."Наименование" AS bb_name FROM {qi(t)} d '
           f'LEFT JOIN participants ps ON ps."ИНН"=d."ИНН продавца" LEFT JOIN participants pb ON pb."ИНН"=d."ИНН покупателя" '
           f'LEFT JOIN brokers bs ON bs."Код брокера"=d."Брокер продавца" LEFT JOIN brokers bb ON bb."Код брокера"=d."Брокер покупателя" '
           f'WHERE {w} ORDER BY d.date_iso DESC, d.rowid DESC LIMIT {MAX_ROWS}')
    rows = query(conn, sql, params)
    return Result("ok", [deal_card(dict(r), lang) for r in rows], total, t, q=text, summary="\n".join(lines))


def do_search(kind: str, text: str, lang: str, flt: dict = None, source: str = "auto", note: str = "") -> Result:
    flt = flt or {}
    if kind == "auto" and source == "auto" and {"year", "status"} & set(flt):   # deal-only filters -> search deals
        source = "deals"
    if kind == "auto" and source != "auto":      # user picked a specific "document" type
        kind = {"contracts": "contracts", "deals": "deals", "participants": "participant",
                "brokers": "broker", "rates": "rate"}.get(source, "auto")
    with closing(db_connect()) as conn:
        ctx = get_ctx(conn)
        if kind in ("auto", "region", "price", "contracts"):
            q = parse_query(text, ctx.regions_lc)
            if kind == "region" and not q.regions:
                return Result("no_region", note=", ".join(sorted({r.title() for r in ctx.regions_lc})[:30]))
            if kind == "price" and q.pmin is None and q.pmax is None:
                return Result("no_price")
            if q.empty and not flt:
                return Result("empty")
            res = search_contracts(conn, ctx, q, lang, text, flt)
            res.flt_note = note
            if res.status in ("ok", "empty") or kind != "auto" or flt:   # no fallback when filters are active
                return res
            # auto-fallback to other tables (still only real DB rows)
            kws = tokens(text)
            for role in ("deals", "participants", "brokers"):
                if role == "deals" and deals_ready(ctx):
                    r2 = search_deals(conn, ctx, q, text, lang)
                    if r2.status == "ok":
                        return r2
                elif ctx.roles[role] and kws:
                    r2 = search_generic(conn, ctx, ctx.roles[role], kws, text)
                    if r2.status == "ok":
                        return r2
            return Result("none", q=text)
        if kind == "deals" and deals_ready(ctx):
            q = parse_query(text, ctx.regions_lc)
            res = search_deals(conn, ctx, q, text, lang, flt)
            res.flt_note = note
            return res
        role = {"deals": "deals", "broker": "brokers", "participant": "participants", "rate": "rates"}[kind]
        tables = ctx.roles[role]
        if not tables:
            return Result("no_table", source=role)
        kws = tokens(text)
        if not kws:
            if kind != "rate":
                return Result("empty")
            t = tables[0]
            order = "date_iso" if "date_iso" in ctx.schema[t] else "rowid"
            rows = query(conn, f"SELECT * FROM {qi(t)} ORDER BY {order} DESC LIMIT 5")
            if not rows:
                return Result("none", q=text)
            return Result("ok", [generic_card(dict(r), t) for r in rows], len(rows), t, note="rate_last", q=text)
        return search_generic(conn, ctx, tables, kws, text)


def do_stats(lang: str) -> str:
    with closing(db_connect()) as conn:
        ctx = get_ctx(conn)
        lines = [b(T[lang]["stats_title"]), ""]
        for role in ("contracts", "deals", "participants", "brokers", "rates"):
            for t in ctx.roles[role]:
                n = query(conn, f"SELECT COUNT(*) FROM {qi(t)}")[0][0]
                lines.append(f"• {e(t)}: {b(fmt_num(str(n)))}")
        if ctx.roles["contracts"]:
            t = ctx.roles["contracts"][0]
            if ctx.c.get("region"):
                n = query(conn, f"SELECT COUNT(DISTINCT {qi(ctx.c['region'])}) FROM {qi(t)}")[0][0]
                lines.append(f"• {e(T[lang]['regions_cnt'])}: {b(n)}")
            if ctx.c.get("name"):
                n = query(conn, f"SELECT COUNT(DISTINCT {qi(ctx.c['name'])}) FROM {qi(t)}")[0][0]
                lines.append(f"• {e(T[lang]['products_cnt'])}: {b(n)}")
        if deals_ready(ctx):
            dt = ctx.roles["deals"][0]
            mn, mx = query(conn, f"SELECT MIN(date_iso), MAX(date_iso) FROM {qi(dt)}")[0]
            yrs = query(conn, f"SELECT year, COUNT(*) AS n FROM {qi(dt)} GROUP BY year ORDER BY year")
            lines.append(f"• {e(mn)} → {e(mx)}")
            lines.append("• " + e(" · ".join(f"{r['year']}: {fmt_num(str(r['n']))}" for r in yrs)))
        return "\n".join(lines)


# ───────────────────────────── User state ─────────────────────────────
_lang: dict = {}
CACHE: "OrderedDict[str, tuple]" = OrderedDict()   # result id -> (Result, lang)


def state_init():
    try:
        with closing(sqlite3.connect(STATE_DB)) as c:
            c.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, lang TEXT NOT NULL)")
            c.commit()
    except sqlite3.Error:
        log.exception("state db init failed (falling back to memory)")


def get_lang(uid: int):
    if uid in _lang:
        return _lang[uid]
    try:
        with closing(sqlite3.connect(STATE_DB, timeout=5)) as c:
            r = c.execute("SELECT lang FROM users WHERE user_id=?", (uid,)).fetchone()
            if r and r[0] in T:
                _lang[uid] = r[0]
                return r[0]
    except sqlite3.Error:
        pass
    return None


def set_lang(uid: int, lang: str):
    _lang[uid] = lang
    try:
        with closing(sqlite3.connect(STATE_DB, timeout=5)) as c:
            c.execute("INSERT INTO users(user_id,lang) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang", (uid, lang))
            c.commit()
    except sqlite3.Error:
        log.warning("could not persist language")


# ───────────────────────────── Telegram helpers ─────────────────────────────
def lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang:uz"),
        InlineKeyboardButton(text="🇷🇺 Русский язык", callback_data="lang:ru")]])


def main_kb(lang):
    t = T[lang]
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text=t["b_search"]), KeyboardButton(text=t["b_stats"])],
        [KeyboardButton(text=t["b_filters"]), KeyboardButton(text=t["b_help"]), KeyboardButton(text=t["b_lang"])]])


async def reply(m: Message, text: str, **kw):
    try:
        return await m.answer(text[:4096], **kw)
    except TelegramBadRequest:
        return await m.answer(plain(text)[:4096], parse_mode=None, **kw)


def render(res: Result, rid: str, offset: int, lang: str):
    t = T[lang]
    n = PAGE_SIZE
    while True:
        chunk = res.items[offset:offset + n]
        end = offset + len(chunk)
        head = [f"{e(t['found'])}: {b(res.total)}", f"{e(t['source'])}: {code(res.source)}"]
        if res.flt_note:
            head.append(f"⚙️ {e(res.flt_note)}")
        if res.summary:
            head.append(res.summary)
        if res.note == "rate_last":
            head.append(e(t["rate_last"]))
        if res.total > len(res.items):
            head.append(e(t["capped"].format(n=len(res.items))))
        head.append(f"{e(t['shown'])} {offset + 1}–{end} {e(t['of'])} {len(res.items)}")
        text = "\n".join(head) + "\n\n" + "\n\n".join(chunk)
        if len(text) <= 4000 or n == 1:
            break
        n -= 1
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"pg:{rid}:{max(0, offset - PAGE_SIZE)}"))
    if end < len(res.items):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"pg:{rid}:{end}"))
    return text, (InlineKeyboardMarkup(inline_keyboard=[nav]) if nav else None)


def status_msg(res: Result, kind: str, lang: str) -> str:
    t = T[lang]
    if res.status == "empty":
        return e(t["u_auto" if kind == "auto" else f"u_{kind}"] if f"u_{kind}" in t else t["u_auto"])
    if res.status == "no_price":
        return e(t["u_price"])
    if res.status == "no_region":
        return e(t["no_region"]) + "\n" + e(res.note or "—")
    if res.status == "no_table":
        return e(t["no_table"].format(t=res.source))
    msg = e(t["not_found"].format(q=clip(res.q, 80)))
    if res.flt_note:
        msg += f"\n⚙️ {e(res.flt_note)}\n/filters"
    return msg


async def run(m: Message, lang: str, kind: str, text: str):
    t = T[lang]
    text = (text or "").strip()
    uid = m.from_user.id
    flt, source, note = active_filters(uid), ufilt(uid)["source"], filt_note(uid, lang)
    if kind == "price" and re.fullmatch(rf"{NUM}\s+{NUM}", norm(text)):   # "/price 100 500"
        a, c = norm(text).split()[0], norm(text).split()[-1]
        text = f"от {a} до {c}"
    if not text and kind != "rate" and not (kind == "auto" and flt):
        return await reply(m, e(t["u_auto" if kind == "auto" else f"u_{kind}"]))
    if len(text) > MAX_QUERY_LEN:
        return await reply(m, e(t["too_long"].format(n=MAX_QUERY_LEN)))
    try:
        await m.bot.send_chat_action(m.chat.id, "typing")
    except Exception:
        pass
    try:
        res = await asyncio.to_thread(do_search, kind, text, lang, flt, source, note)
    except Exception:
        log.exception("search failed: kind=%s text=%r", kind, text)
        return await reply(m, e(t["db_error"]))
    if res.status != "ok":
        return await reply(m, status_msg(res, kind, lang))
    rid = uuid.uuid4().hex[:10]
    CACHE[rid] = (res, lang)
    while len(CACHE) > 300:
        CACHE.popitem(last=False)
    txt, kb = render(res, rid, 0, lang)
    await reply(m, txt, reply_markup=kb)


async def ensure_lang(m: Message):
    lang = get_lang(m.from_user.id) if m.from_user else None
    if not lang:
        await m.answer(CHOOSE_LANG, parse_mode=None, reply_markup=lang_kb())
    return lang


# ───────────────────────────── Handlers ─────────────────────────────
@router.message(CommandStart())
@router.message(Command("lang"))
async def cmd_start(m: Message):
    await m.answer(CHOOSE_LANG, parse_mode=None, reply_markup=lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(cb: CallbackQuery):
    lang = cb.data.split(":", 1)[1]
    if lang not in T:
        return await cb.answer()
    set_lang(cb.from_user.id, lang)
    await cb.answer(plain(T[lang]["lang_saved"]))
    if cb.message:
        await cb.message.answer(e(T[lang]["welcome"]), reply_markup=main_kb(lang))


@router.callback_query(F.data.startswith("pg:"))
async def cb_page(cb: CallbackQuery):
    try:
        _, rid, off = cb.data.split(":")
        res, lang = CACHE[rid]
        text, kb = render(res, rid, max(0, int(off)), lang)
    except (KeyError, ValueError):
        lang = get_lang(cb.from_user.id) or "ru"
        return await cb.answer(T[lang]["expired"], show_alert=True)
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as ex:
        if "not modified" not in str(ex):
            try:
                await cb.message.edit_text(plain(text), parse_mode=None, reply_markup=kb)
            except TelegramBadRequest:
                pass
    await cb.answer()


# ───────────────────────── Filters UI (source + multi-select filters) ─────────────────────────
FILTERS: dict = {}   # uid -> {"source": str, "sel": {field: set(values)}}
PICK: dict = {}      # (uid, field) -> value list shown in the picker


def ufilt(uid: int) -> dict:
    return FILTERS.setdefault(uid, {"source": "auto", "sel": {k: set() for k in FIELDS}})


def active_filters(uid: int) -> dict:
    return {k: set(v) for k, v in ufilt(uid)["sel"].items() if v}


def flab(k: str, lang: str) -> str:
    return FIELDS[k][1 if lang == "ru" else 2]


def filt_note(uid: int, lang: str) -> str:
    parts = [f"{flab(k, lang)}: {clip(', '.join(sorted(v)), 80)}" for k, v in active_filters(uid).items()]
    return " · ".join(parts)


def load_ctx() -> Ctx:
    with closing(db_connect()) as conn:
        return get_ctx(conn)


def load_values(field_key: str) -> list:
    with closing(db_connect()) as conn:
        ctx = get_ctx(conn)
        if field_key in ctx.vals:
            return ctx.vals[field_key]
        vals = []
        for table, role in (("contracts", "contracts"), ("deals", "deals")):
            col, tabs = fcol(ctx, field_key, table), ctx.roles[role]
            if col and tabs:
                order = "v DESC" if field_key == "year" else "n DESC"
                rows = query(conn, f"SELECT {qi(col)} AS v, COUNT(*) AS n FROM {qi(tabs[0])} WHERE {qi(col)} IS NOT NULL "
                                   f"AND TRIM({qi(col)})<>'' GROUP BY {qi(col)} ORDER BY {order} LIMIT 200")
                vals = [str(r["v"]) for r in rows]
                break
        ctx.vals[field_key] = vals
        return vals


def ibtn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def menu_view(uid: int, lang: str, ctx: Ctx):
    t, st = T[lang], ufilt(uid)
    lines = [b(t["f_title"]), "", f"📂 {b(t['f_source'])}: {e(SRC[st['source']][0 if lang == 'ru' else 1])}"]
    rows = [[ibtn("📂 " + t["f_source"], "f:src")]]
    btns = []
    for k, (ic, _, _) in FIELDS.items():
        if not (fcol(ctx, k, "contracts") or fcol(ctx, k, "deals")):
            continue
        sel = st["sel"][k]
        lines.append(f"{ic} {b(flab(k, lang))}: {e(clip(', '.join(sorted(sel)), 80)) if sel else e(t['f_none'])}")
        btns.append(ibtn(f"{ic} {flab(k, lang)}" + (f" ({len(sel)})" if sel else ""), f"f:v:{k}:0"))
    rows += [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([ibtn(t["f_clear_all"], "f:c"), ibtn(t["f_done"], "f:close")])
    lines += ["", e(t["f_hint"])]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def source_view(uid: int, lang: str, ctx: Ctx):
    t, cur = T[lang], ufilt(uid)["source"]
    ok = {"auto": True, **{k: bool(ctx.roles.get(k)) for k in SRC if k != "auto"}}
    btns = [ibtn(("✅ " if k == cur else "") + SRC[k][0 if lang == "ru" else 1], f"f:s:{k}") for k in SRC if ok[k]]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)] + [[ibtn(t["f_back"], "f:menu")]]
    return f"{b(t['f_source'])}\n{e(t['f_pick_src'])}", InlineKeyboardMarkup(inline_keyboard=rows)


def picker_view(uid: int, lang: str, k: str, page: int, vals: list):
    t, sel = T[lang], ufilt(uid)["sel"][k]
    pages = max(1, -(-len(vals) // PER_PICK))
    page = min(max(page, 0), pages - 1)
    btns = [ibtn(("✅ " if v in sel else "") + clip(v, 28), f"f:t:{k}:{i}")
            for i, v in enumerate(vals) if page * PER_PICK <= i < (page + 1) * PER_PICK]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    nav = []
    if page > 0:
        nav.append(ibtn("⬅️", f"f:v:{k}:{page - 1}"))
    nav.append(ibtn(f"{page + 1}/{pages}", "f:noop"))
    if page < pages - 1:
        nav.append(ibtn("➡️", f"f:v:{k}:{page + 1}"))
    rows += [nav, [ibtn(t["f_clear"], f"f:x:{k}"), ibtn(t["f_done"], "f:menu")]]
    text = f"{FIELDS[k][0]} {b(flab(k, lang))}\n{e(t['f_pick'])}"
    if sel:
        text += f"\n✅ {e(clip(', '.join(sorted(sel)), 200))}"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def safe_edit(msg, text, kb):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as ex:
        if "not modified" not in str(ex):
            try:
                await msg.edit_text(plain(text), parse_mode=None, reply_markup=kb)
            except TelegramBadRequest:
                pass


@router.message(Command("filters"))
async def cmd_filters(m: Message):
    lang = await ensure_lang(m)
    if not lang:
        return
    try:
        ctx = await asyncio.to_thread(load_ctx)
    except Exception:
        log.exception("filters failed")
        return await reply(m, e(T[lang]["db_error"]))
    text, kb = menu_view(m.from_user.id, lang, ctx)
    await reply(m, text, reply_markup=kb)


@router.callback_query(F.data.startswith("f:"))
async def cb_filters(cb: CallbackQuery):
    uid, lang = cb.from_user.id, get_lang(cb.from_user.id) or "ru"
    p, st = cb.data.split(":"), ufilt(cb.from_user.id)
    try:
        act = p[1]
        if act == "noop":
            return await cb.answer()
        if act == "close":
            await cb.answer()
            try:
                return await cb.message.delete()
            except TelegramBadRequest:
                return
        ctx = await asyncio.to_thread(load_ctx)
        if act == "s" and p[2] in SRC:
            st["source"] = p[2]
        elif act == "c":
            FILTERS.pop(uid, None)
        elif act in ("x", "v", "t") and p[2] in FIELDS:
            k = p[2]
            if act == "x":
                st["sel"][k].clear()
            else:
                vals = PICK.get((uid, k))
                if act == "v" and (p[3] == "0" or not vals):
                    vals = PICK[(uid, k)] = await asyncio.to_thread(load_values, k)
                vals = vals or await asyncio.to_thread(load_values, k)
                PICK[(uid, k)] = vals
                idx = int(p[3])
                if act == "t" and 0 <= idx < len(vals):
                    st["sel"][k] ^= {vals[idx]}
                page = idx // PER_PICK if act == "t" else idx
                text, kb = picker_view(uid, lang, k, page, vals)
                await safe_edit(cb.message, text, kb)
                return await cb.answer()
        if act == "src":
            text, kb = source_view(uid, lang, ctx)
        else:
            text, kb = menu_view(uid, lang, ctx)
        await safe_edit(cb.message, text, kb)
        await cb.answer()
    except (ValueError, IndexError):
        await cb.answer()
    except sqlite3.Error:
        log.exception("filter callback db error")
        await cb.answer(plain(T[lang]["db_error"]), show_alert=True)


@router.message(Command("help"))
async def cmd_help(m: Message):
    if lang := await ensure_lang(m):
        await reply(m, e(T[lang]["help"]))


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if lang := await ensure_lang(m):
        try:
            await reply(m, await asyncio.to_thread(do_stats, lang))
        except Exception:
            log.exception("stats failed")
            await reply(m, e(T[lang]["db_error"]))


@router.message(Command("region", "price", "deals", "broker", "participant", "rate"))
async def cmd_search(m: Message, command: CommandObject):
    if lang := await ensure_lang(m):
        await run(m, lang, command.command.lower(), command.args or "")


@router.message(F.text.startswith("/"))
async def cmd_unknown(m: Message):
    if lang := await ensure_lang(m):
        await reply(m, e(T[lang]["unknown_cmd"]))


@router.message(F.text)
async def on_text(m: Message):
    lang = await ensure_lang(m)
    if not lang:
        return
    txt = (m.text or "").strip()
    t = T[lang]
    if txt == t["b_help"]:
        return await reply(m, e(t["help"]))
    if txt == t["b_lang"]:
        return await cmd_start(m)
    if txt == t["b_stats"]:
        return await cmd_stats(m)
    if txt == t["b_filters"]:
        return await cmd_filters(m)
    if txt == t["b_search"]:
        if active_filters(m.from_user.id):      # filters chosen -> browse with them right away
            return await run(m, lang, "auto", "")
        return await reply(m, e(t["ask_query"]))
    await run(m, lang, "auto", txt)


@router.message()
async def on_other(m: Message):
    lang = await ensure_lang(m)
    if lang:
        await reply(m, e(T[lang]["unsupported"]))


@router.error()
async def on_error(event: ErrorEvent):
    log.exception("Unhandled error: %s", event.exception)
    msg = event.update.message or (event.update.callback_query.message if event.update.callback_query else None)
    if msg:
        try:
            lang = get_lang(msg.chat.id) or "ru"
            await msg.answer(plain(T[lang]["db_error"]), parse_mode=None)
        except Exception:
            pass
    return True


async def main():
    if not BOT_TOKEN:
        raise SystemExit("Set the BOT_TOKEN environment variable.")
    state_init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Bot started (DB: %s)", DB_PATH)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
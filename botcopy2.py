import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pytesseract
import fitz
import re
import os
from tempfile import mkdtemp
from PIL import Image
from pdf2image import convert_from_path

# === НАСТРОЙКИ ===
TOKEN = ""
TESSERACT_PATH = "/usr/bin/tesseract"
POPPLER_PATH = "/usr/bin"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
bot = telebot.TeleBot(TOKEN)

user_state = {}

def extract_text_from_file(path):
    if path.lower().endswith(".pdf"):
        try:
            # 1. Пробуем как текстовый PDF
            with fitz.open(path) as doc:
                text = "".join([page.get_text() for page in doc])
            if text.strip():
                return text
        except:
            pass
        # 2. Пробуем как картинку
        try:
            images = convert_from_path(path, poppler_path=POPPLER_PATH)
            return "\n".join([pytesseract.image_to_string(img, lang="deu") for img in images])
        except:
            return ""
    else:
        try:
            img = Image.open(path)
            return pytesseract.image_to_string(img, lang="deu")
        except:
            return ""

def parse_products_from_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    try:
        preis_idx = next(i for i, l in enumerate(lines) if "Preis EUR" in l)
    except StopIteration:
        preis_idx = -1
    try:
        summe_idx = next(i for i, l in enumerate(lines) if "Zwischensumme" in l)
    except StopIteration:
        summe_idx = len(lines)

    names_block = lines[5:preis_idx]
    prices_block = lines[preis_idx+1:summe_idx]

    price_pattern = re.compile(r"[-+]?\d{1,3}[,.]\d{2}")
    valid_prices = [p.replace(",", ".") for p in prices_block if price_pattern.fullmatch(p.replace("€", "").strip())]

    products = []
    for i in range(min(len(names_block), len(valid_prices))):
        products.append({
            "name": names_block[i],
            "price": float(valid_prices[i])
        })

    rabatt_match = re.search(r"K\s*Card\s*Rabatt\s*[-–](\d{1,3}[,.]\d{2})", text)
    discount = float(rabatt_match.group(1).replace(",", ".")) if rabatt_match else 0.0

    return products, discount

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Привет! Отправь PDF или фото чека 🧾 — я помогу поделить.")

@bot.message_handler(content_types=['document', 'photo'])
def handle_file(message):
    temp_dir = mkdtemp()
    if message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        file_path = os.path.join(temp_dir, message.document.file_name)
    elif message.content_type == 'photo':
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        file_path = os.path.join(temp_dir, "photo.jpg")
    else:
        return

    with open(file_path, "wb") as f:
        f.write(downloaded)

    bot.send_message(message.chat.id, "🔍 Распознаю чек...")
    text = extract_text_from_file(file_path)

    if not text.strip():
        bot.send_message(message.chat.id, "❌ Не удалось прочитать текст.")
        return

    products, discount = parse_products_from_text(text)
    if not products:
        bot.send_message(message.chat.id, "❌ Не удалось найти товары.")
        return

    user_state[message.chat.id] = {
        "products": products,
        "discount": discount,
        "index": 0,
        "confirmed": [],
        "personal": []
    }

    send_next_product(message.chat.id)

def send_next_product(chat_id):
    state = user_state.get(chat_id)
    if state is None or state["index"] >= len(state["products"]):
        confirmed = state["confirmed"]
        personal = state["personal"]
        discount = state.get("discount", 0)

        total = sum(p["price"] for p in confirmed) - discount
        personal_total = sum(p["price"] for p in personal)
        shared_total = total - personal_total
        brother_owes = round(shared_total / 2, 2)

        msg = f"✅ Готово!\n💰 Сумма: {total:.2f} €"
        if discount > 0:
            msg += f"\n💸 Скидка: -{discount:.2f} €"
        msg += f"\n🔒 Лично твоё: {personal_total:.2f} €"
        msg += f"\n🤝 Брат должен тебе: {brother_owes:.2f} €"
        bot.send_message(chat_id, msg)
        return

    product = state["products"][state["index"]]
    name, price = product["name"], product["price"]

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Всё верно", callback_data="accept"),
        InlineKeyboardButton("✏️ Исправить", callback_data="edit")
    )
    markup.row(
        InlineKeyboardButton("🔒 Только моё", callback_data="personal"),
        InlineKeyboardButton("❌ Удалить", callback_data="delete")
    )

    bot.send_message(chat_id, f"{name}\nЦена: {price:.2f} €", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    state = user_state.get(chat_id)
    product = state["products"][state["index"]]

    if call.data == "accept":
        state["confirmed"].append(product)
    elif call.data == "personal":
        state["confirmed"].append(product)
        state["personal"].append(product)
    elif call.data == "edit":
        msg = bot.send_message(chat_id, "✏️ Введи цену:")
        bot.register_next_step_handler(msg, lambda m: handle_price_edit(m, chat_id))
        return

    state["index"] += 1
    send_next_product(chat_id)

def handle_price_edit(message, chat_id):
    state = user_state.get(chat_id)
    try:
        new_price = float(message.text.replace(",", "."))
        current = state["products"][state["index"]]
        current["price"] = new_price
        state["confirmed"].append(current)
    except:
        bot.send_message(chat_id, "❌ Неверный формат.")
    state["index"] += 1
    send_next_product(chat_id)

bot.polling()

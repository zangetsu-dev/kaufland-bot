import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pdf2image import convert_from_path
import pytesseract
import fitz  # PyMuPDF
import re
import os
from tempfile import mkdtemp

# === НАСТРОЙКИ ===
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")  # токен читается из переменной окружения
bot = telebot.TeleBot(TOKEN)

# === СОСТОЯНИЕ ===
user_state = {}

# === ИЗВЛЕЧЕНИЕ ТЕКСТА ИЗ PDF ===
def extract_products_from_pdf(pdf_path):
    try:
        with fitz.open(pdf_path) as doc:
            extracted_text = "".join([page.get_text() for page in doc])
        if len(extracted_text.strip()) > 0:
            print("📄 Извлечён текст напрямую из PDF")
            full_text = extracted_text
        else:
            raise Exception("PDF пустой")
    except:
        images = convert_from_path(pdf_path)
        full_text = ""
        for img in images:
            full_text += pytesseract.image_to_string(img, lang="deu")
        print("🔍 Использован OCR через Tesseract")

    products = []
    for line in full_text.splitlines():
        line = line.strip()
        if not line or any(x in line.lower() for x in ["preis", "summe", "rabatt", "kartenzahlung"]):
            continue
        match = re.search(r"(.+?)\s+(\d{1,3},\d{2})\s?([AB])\b", line)
        if match:
            name = match.group(1).strip()
            price = float(match.group(2).replace(",", "."))
            tax = match.group(3)
            products.append({"name": name, "price": price, "tax": tax})

    rabatt_match = re.search(r"K\s*Card\s*Rabatt\s*[-–](\d{1,3},\d{2})", full_text)
    discount = float(rabatt_match.group(1).replace(",", ".")) if rabatt_match else 0.0

    return products, discount

# === /start ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Привет! Отправь мне PDF-чек из Kaufland 🧾 — я помогу посчитать и поделить покупки.")

# === ПРИНИМАЕМ PDF ===
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    temp_dir = mkdtemp()
    file_path = os.path.join(temp_dir, message.document.file_name)

    with open(file_path, 'wb') as new_file:
        new_file.write(downloaded_file)

    bot.send_message(message.chat.id, "🔄 Обрабатываю чек...")
    products, discount = extract_products_from_pdf(file_path)

    if not products:
        bot.send_message(message.chat.id, "❌ Не удалось найти товары в чеке.")
        return

    user_state[message.chat.id] = {
        "products": products,
        "discount": discount,
        "index": 0,
        "confirmed": [],
        "personal": []
    }

    send_next_product(message.chat.id)

# === СЛЕДУЮЩИЙ ТОВАР ===
def send_next_product(chat_id):
    state = user_state.get(chat_id)
    if state is None:
        return

    if state["index"] >= len(state["products"]):
        confirmed = state["confirmed"]
        personal = state["personal"]
        discount = state.get("discount", 0)

        total = sum(p["price"] for p in confirmed) - discount
        personal_total = sum(p["price"] for p in personal)
        shared_total = total - personal_total
        brother_owes = round(shared_total / 2, 2)

        msg = f"✅ Все товары подтверждены!\n\n"
        msg += f"💰 Общая сумма: {total:.2f} €"
        if discount > 0:
            msg += f"\n💸 Учтена скидка Kaufland Card: -{discount:.2f} €"
        msg += f"\n🔒 Твои личные товары: {personal_total:.2f} €"
        msg += f"\n🤝 Брат должен тебе: {brother_owes:.2f} €"

        bot.send_message(chat_id, msg)
        return

    product = state["products"][state["index"]]
    name = product["name"]
    price = product["price"]

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

# === КНОПКИ ===
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    state = user_state.get(chat_id)
    if state is None:
        return

    product = state["products"][state["index"]]

    if call.data == "accept":
        state["confirmed"].append(product)
    elif call.data == "personal":
        state["confirmed"].append(product)
        state["personal"].append(product)
    elif call.data == "edit":
        msg = bot.send_message(chat_id, "✏️ Введи правильную цену:")
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

# === СТАРТ ===
bot.polling()

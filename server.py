from flask import Flask, render_template, request, jsonify
import os, requests, re, time, json, uuid
from bs4 import BeautifulSoup
from werkzeug.utils import secure_filename
from collections import defaultdict

app = Flask(__name__, template_folder="templates", static_folder="static")

UPLOAD_FOLDER = "uploads"
USERS_FILE = "users.json"
ALLOWED_EXTENSIONS = {
    "txt", "pdf", "docx",
    "py", "html", "css", "js", "json", "md", "csv",
    "jpg", "jpeg", "png", "gif", "bmp", "webp"
}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/XXXX/XXXX"  # đổi webhook thật

# Load user data
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        USERS = json.load(f)
else:
    USERS = {}  # username: {password, gender, history:{}}

SESSIONS = {}  # session_token: username

# Groq API config
GROQ_API_KEYS = [
    "gsk_KEY1",
    "gsk_KEY2",
    "gsk_KEY3"
]
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"
CURRENT_KEY_INDEX = 0  # nhớ vị trí key đang dùng

CONVERSATIONS = {}
PENDING_FILE_CONTENT = {}
MAX_HISTORY_MESSAGES = 20

SYSTEM_PROMPT = (
    "Bạn là Furina, một cô gái dễ thương 🥰✨💕, xưng 'em' và gọi người nói chuyện là 'anh' hoặc 'chị' tùy giới tính."
)

USER_MESSAGES = defaultdict(list)
BANNED_IPS = {}

# --- Helper ---
def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(USERS, f, ensure_ascii=False, indent=2)

def send_users_to_discord():
    try:
        with open(USERS_FILE, "rb") as f:
            files = {"file": ("users.json", f, "application/json")}
            requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=10)
    except Exception as e:
        print("Lỗi gửi user.json lên Discord:", e)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def build_payload(messages):
    return {"model": MODEL, "messages": messages, "temperature": 0.7, "max_tokens": 512}

def call_groq(messages):
    """Luân phiên API key, bỏ qua key lỗi/hết quota ngay lập tức"""
    global CURRENT_KEY_INDEX
    last_error = None
    num_keys = len(GROQ_API_KEYS)

    for attempt in range(num_keys):
        key_index = (CURRENT_KEY_INDEX + attempt) % num_keys
        key = GROQ_API_KEYS[key_index]

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(
                GROQ_API_URL,
                headers=headers,
                json=build_payload(messages),
                timeout=60
            )
        except requests.RequestException as e:
            last_error = f"Lỗi kết nối API key {key_index+1}: {e}"
            continue

        if resp.status_code == 200:
            CURRENT_KEY_INDEX = (key_index + 1) % num_keys
            return {"success": True, "data": resp.json()}
        else:
            try:
                err_json = resp.json()
                err_msg = err_json.get("error", {}).get("message", "") or resp.text
            except:
                err_msg = resp.text
            last_error = f"Key {key_index+1} lỗi: {err_msg}"
            continue

    return {"success": False, "error": last_error or "Tất cả key Groq đều lỗi/hết quota"}

# --- Auth APIs ---
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    repassword = (data.get("repassword") or "").strip()
    gender = (data.get("gender") or "").strip().lower()
    captcha = (data.get("captcha") or "").strip()

    if captcha != "1234":
        return jsonify({"error": "Sai captcha"}), 400
    if not username or not password or not repassword or not gender:
        return jsonify({"error": "Thiếu thông tin"}), 400
    if gender not in {"male", "female"}:
        return jsonify({"error": "Giới tính không hợp lệ"}), 400
    if password != repassword:
        return jsonify({"error": "Mật khẩu nhập lại không khớp"}), 400
    if username in USERS:
        return jsonify({"error": "Username đã tồn tại"}), 400

    USERS[username] = {
        "password": password,
        "gender": gender,
        "history": {}
    }
    save_users()
    send_users_to_discord()
    return jsonify({"success": True, "message": "Đăng ký thành công"})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if username not in USERS or USERS[username]["password"] != password:
        return jsonify({"error": "Sai username hoặc password"}), 400

    session_token = str(uuid.uuid4())
    SESSIONS[session_token] = username
    return jsonify({"success": True, "session": session_token, "gender": USERS[username]["gender"]})

# --- Chat API ---
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    session_token = data.get("session", "").strip()
    if session_token not in SESSIONS:
        return jsonify({"error": "Chưa đăng nhập"}), 403

    username = SESSIONS[session_token]
    gender = USERS[username]["gender"]
    honorific = "anh" if gender == "male" else "chị"

    message = (data.get("message") or "").strip()
    conv_id = (data.get("conversationId") or "").strip()
    if not message:
        return jsonify({"error": "Nội dung trống"}), 400
    if not conv_id:
        conv_id = str(int(time.time() * 1000))

    if conv_id not in CONVERSATIONS:
        prompt_with_gender = SYSTEM_PROMPT + f" Khi trò chuyện, bạn gọi người dùng là '{honorific}' và biết họ tên là {username}."
        CONVERSATIONS[conv_id] = [{"role": "system", "content": prompt_with_gender}]

    if conv_id in PENDING_FILE_CONTENT:
        file_text = PENDING_FILE_CONTENT.pop(conv_id)
        message = f"Phân tích file:\n{file_text}\n\nCâu hỏi: {message}"

    CONVERSATIONS[conv_id].append({"role": "user", "content": message})
    USERS[username]["history"].setdefault(conv_id, []).append({"role": "user", "content": message})
    save_users()

    base = CONVERSATIONS[conv_id][0:1]
    tail = CONVERSATIONS[conv_id][-2 * MAX_HISTORY_MESSAGES:]
    messages = base + tail

    result = call_groq(messages)
    if result.get("success"):
        reply = result["data"]["choices"][0]["message"]["content"].strip()
        CONVERSATIONS[conv_id].append({"role": "assistant", "content": reply})
        USERS[username]["history"][conv_id].append({"role": "assistant", "content": reply})
        save_users()
        return jsonify({"reply": reply, "conversationId": conv_id})

    return jsonify({"error": result.get("error", "Lỗi không xác định")}), 500

# --- File upload ---
@app.route("/api/upload", methods=["POST"])
def upload_file():
    conv_id = request.form.get("conversationId", "").strip()
    if not conv_id:
        return jsonify({"error": "Thiếu conversationId"}), 400

    if "file" not in request.files:
        return jsonify({"error": "Không có file"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Tên file trống"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Định dạng file không được hỗ trợ"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)

    ext = filename.rsplit(".", 1)[1].lower()
    try:
        if ext in {"txt", "md", "csv", "json", "py", "html", "css", "js"}:
            with open(save_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        else:
            content = f"[File {filename} đã tải lên, định dạng nhị phân hoặc không đọc được.]"
    except Exception as e:
        content = f"[Không thể đọc file: {e}]"

    PENDING_FILE_CONTENT[conv_id] = content
    return jsonify({"success": True, "filename": filename})

@app.route("/")
def index():
    return render_template("index.html", model_name=MODEL)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

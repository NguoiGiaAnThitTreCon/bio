import os
from flask import Flask, render_template, url_for

app = Flask(__name__, static_folder='static')

# ====== cấu hình (thay bằng link bạn muốn) ======
FB_LINK = "https://www.facebook.com/NguyenTrong6565"
DISCORD_LINK = "https://discord.gg/bpZqKr2EWQ"
USERNAME = "Nguyen Trong"
BIO_LINE = "Anh Trọng chim dài, còn em đóng vai người chồng bất lực nhìn vợ mình xa theo anh Trọng."
BANNER_FILE = "banner.mp4"
AVATAR_FILE = "avatar.png"
MUSIC_FILE = "music.mp3"
# ================================================

def static_if_exists(fname):
    path = os.path.join(app.root_path, "static", fname)
    return url_for('static', filename=fname) if os.path.exists(path) else None

@app.route("/")
def home():
    return render_template(
        "index.html",
        fb_link=FB_LINK,
        discord_link=DISCORD_LINK,
        username=USERNAME,
        bio_line=BIO_LINE,
        banner_url=static_if_exists(BANNER_FILE),
        avatar_url=static_if_exists(AVATAR_FILE),
        music_url=static_if_exists(MUSIC_FILE),
    )

if __name__ == "__main__":
    # debug=True khi dev, tắt khi deploy
    app.run(host="0.0.0.0", port=5000, debug=True)

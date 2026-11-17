# SubForge on Raspberry Pi (ARM64)

SubForge uses cloud ASR APIs (OpenAI Whisper / Groq / DeepSeek ASR / Deepgram / Gemini) and lightweight `ffmpeg` audio chunking, so it runs comfortably on a Raspberry Pi (`raspb` / ARM64) without PyTorch, CUDA, or local Whisper models.

## 1. Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg
```

## 2. Install SubForge

```bash
git clone https://github.com/LosLiSang/subforge.git
cd subforge
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install .
```

## 3. Run with Tailscale HTTPS (Recommended for Mobile PWA)

Keep SubForge bound to `127.0.0.1:8765` and expose it over HTTPS using Tailscale Serve (required for mobile PWA installability and Service Worker support):

```bash
# Start SubForge (set a fixed token for mobile auth, or --no-auth on trusted tailnet)
.venv/bin/subforge ui --host 127.0.0.1 --port 8765 --no-browser --token YOUR_SECRET_TOKEN

# In another terminal (persists across reboots):
tailscale serve --bg http://127.0.0.1:8765
```

Open `https://<your-pi>.<tailnet>.ts.net/?token=YOUR_SECRET_TOKEN` on your phone, then use **Add to Home Screen** (iOS Safari) or **Install App** (Android Chrome).

## 4. Run as a systemd Service

1. Edit `deploy/rpi/subforge-ui.service` to match your username (`User=`), `.venv/bin/subforge` path, and `--token` (or `--no-auth`).
2. Install and enable the service:

```bash
sudo cp deploy/rpi/subforge-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now subforge-ui
sudo systemctl status subforge-ui
```

## 5. Docker Alternative

```bash
docker build -t subforge .
docker run -d --name subforge \
  -p 127.0.0.1:8765:8765 \
  -v ~/.subforge:/root/.subforge \
  -v /path/to/library:/library \
  subforge
```

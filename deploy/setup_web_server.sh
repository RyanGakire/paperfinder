#! /usr/bin/env bash
# Installs or updates PaperFinder on a web server (run on web-01 and web-02).
# Usage: sudo ./setup_web_server.sh https://github.com/YOUR_USERNAME/paperfinder.git
set -euo pipefail

REPO_URL="${1:?Usage: sudo ./setup_web_server.sh REPO_URL}"
APP_DIR=/opt/paperfinder
NGINX_SITE=/etc/nginx/sites-available/default

echo "==> Installing system packages"
apt-get update -y
apt-get install -y git nginx python3-venv

echo "==> Getting the code"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$APP_DIR"
fi

echo "==> Installing Python packages"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Preparing the .env file (keeps the API key off Github)"
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "  Created $APP_DIR/.env - add your OPENALEX_API_KEY there."
fi
chown www-data:www-data "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "==> Starting the app as a service"
cp "$APP_DIR/deploy/paperfinder.service" /etc/systemd/system/paperfinder.service
systemctl daemon-reload
systemctl enable paperfinder
systemctl restart paperfinder

echo "==> Connecting Nginx to the app at /papers/"
cp "$APP_DIR/deploy/nginx-paperfinder.conf" /etc/nginx/snippets/paperfinder/conf
if ! grep -q "snippets/paperfinder.conf" "$NGINX_SITE"; then
    sed -i '0,/server_name _;/s//server_name _;\n\n     include snippets\/paperfinder.conf;/' "$NGINX_SITE"
fi
nginx -t
service nginx reload

echo "==> Checking the app answers"
sleep 2
curl -s http://127.0.0.1/papers/api/health
echo
echo "==> Done. Visit http://SERVER_IP/papers/"
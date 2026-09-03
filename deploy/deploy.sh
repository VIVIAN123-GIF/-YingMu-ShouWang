#!/usr/bin/env bash
# =============================================================================
# YingMu ShouWang - Tencent Lighthouse 一键部署脚本
# 目标服务器：49.232.205.215 (北京七区, 2核2GB)
# 用法：在服务器上 /root 下执行  bash deploy.sh
# 前提：本项目源码已上传至 /opt/yingmu（本脚本与源码同级运行时自动定位）
# =============================================================================
set -euo pipefail

APP_DIR="/opt/yingmu"
SERVICE_NAMES=("yingmu-api" "yingmu-alarm-worker" "yingmu-agent-worker")
DB_PATH="${YINGMU_DB_PATH:-/opt/yingmu/runtime/app.db}"

log() { echo -e "\n\033[1;32m[$1]\033[0m $2"; }
warn() { echo -e "\033[1;33m[!]\033[0m $1"; }

# 0. 确认目录
if [ ! -d "$APP_DIR/backend" ]; then
  warn "未在 $APP_DIR 找到 backend，请先把项目源码解压/上传到 $APP_DIR"
  exit 1
fi
cd "$APP_DIR"

# 1. 系统依赖
log "1/8" "安装系统依赖 (ffmpeg 等)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ffmpeg nginx python3-venv python3-pip

# 2. Python 虚拟环境
log "2/8" "创建 Python 虚拟环境 .venv ..."
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
# audio-behavior-demo 依赖（PYTHONPATH 会引用其 src）
if [ -f "$APP_DIR/deliverables/cym/audio-behavior-demo/requirements.txt" ]; then
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/deliverables/cym/audio-behavior-demo/requirements.txt" || warn "audio-behavior-demo 依赖安装失败（可忽略，若语音任务不启用）"
fi

# 3. 运行时目录与 .env
log "3/8" "准备运行时目录与 .env ..."
mkdir -p "$APP_DIR/runtime/private-media" "$APP_DIR/runtime/logs" /var/lib/yingmu/private-media
if [ ! -f "$APP_DIR/.env" ]; then
  warn "未找到 $APP_DIR/.env，请手动上传 yingmu-server.env 并改名为 .env"
  exit 1
fi
# 关键配置兜底校验
grep -q '^YINGMU_MEDIA_AUTO_SESSION' "$APP_DIR/.env" || echo 'YINGMU_MEDIA_AUTO_SESSION=true' >> "$APP_DIR/.env"
grep -q '^YINGMU_PRIVATE_MEDIA_ROOT=/var/lib/yingmu/private-media' "$APP_DIR/.env" || \
  sed -i 's#^YINGMU_PRIVATE_MEDIA_ROOT=.*#YINGMU_PRIVATE_MEDIA_ROOT=/var/lib/yingmu/private-media#' "$APP_DIR/.env"

# 4. 初始化数据库（空库，若已存在跳过）
log "4/8" "初始化数据库..."
if [ ! -f "$DB_PATH" ]; then
  (cd "$APP_DIR" && ./.venv/bin/python -c "import asyncio; from backend.db.init_db import init_tables, init_default_config; from backend.db.database import AsyncSessionLocal
import asyncio
async def _run():
    from backend.db.init_db import init_tables, init_default_config
    from backend.db.database import AsyncSessionLocal
    await init_tables()
    async with AsyncSessionLocal() as s:
        await init_default_config(s)
asyncio.run(_run())")
fi

# 5. 安装 systemd 服务
log "5/8" "安装 systemd 服务..."
for s in "${SERVICE_NAMES[@]}"; do
  cp -f "$APP_DIR/deploy/$s.service" "/etc/systemd/system/$s.service"
done
systemctl daemon-reload

# 6. 配置 nginx（80 → 8002）
log "6/8" "配置 nginx ..."
cp -f "$APP_DIR/deploy/nginx-yingmu.conf" /etc/nginx/sites-available/yingmu
ln -sf /etc/nginx/sites-available/yingmu /etc/nginx/sites-enabled/yingmu
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl enable nginx && systemctl reload nginx || warn "nginx 测试失败，请检查配置"

# 7. 启动服务
log "7/8" "启动服务..."
systemctl enable yingmu-api yingmu-alarm-worker yingmu-agent-worker
systemctl restart yingmu-api yingmu-alarm-worker yingmu-agent-worker
sleep 4

# 8. 验证
log "8/8" "验证..."
echo "--- 服务状态 ---"
systemctl is-active yingmu-api yingmu-alarm-worker yingmu-agent-worker
echo "--- 健康检查 ---"
curl -s --max-time 10 http://127.0.0.1:8002/health || echo "health 失败"
echo
echo "--- 设备状态 ---"
curl -s --max-time 10 http://127.0.0.1:8002/api/v1/device/status || echo "device status 失败"
echo
echo "--- 直播流(头信息) ---"
curl -s -i --max-time 10 -o /dev/null -D - http://127.0.0.1:8002/media/live 2>&1 | head -12 || echo "media/live 失败"
echo
log "DONE" "部署完成。浏览器访问 http://49.232.205.215 查看。"

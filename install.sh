#!/usr/bin/env bash
# ============================================================================
#  云枢MC开服面板 · Linux 一键安装脚本
#
#  与同仓 RT面板（rt-panel）**完全独立、零耦合**：
#    · 不读写它的任何目录/文件/服务/数据库；不检测它是否存在；不向它注册任何东西
#    · 服务名 mc-panel（与 rt-panel 互不干扰）、目录 /opt/mc-panel、数据目录自带
#    · 卸载本面板不会碰到 rt-panel；卸载 rt-panel 也不会影响本面板
#
#  用法：
#    sudo bash install.sh                     # 安装（默认端口 8100）
#    sudo bash install.sh --port 8200         # 指定端口
#    sudo bash install.sh --dir /opt/mc-panel # 指定安装目录
#    sudo bash install.sh --uninstall         # 卸载（会二次确认，默认保留数据）
#
#  脚本做的事：
#    1. 安装系统依赖（python3 / python3-venv / curl / tar）
#    2. 复制程序到 $INSTALL_DIR
#    3. 建虚拟环境并安装 requirements.txt
#    4. 写 systemd 服务 mc-panel 并开机自启
#    5. 初始化数据库；**超级管理员初始口令只在本地终端打印一次**
# ============================================================================
set -euo pipefail

SERVICE_NAME="mc-panel"
INSTALL_DIR="/opt/mc-panel"
DATA_DIR=""
PORT="8100"
BIND_HOST="0.0.0.0"
RUN_USER="mcpanel"
UNINSTALL=0

GOLD=$'\033[38;2;212;175;55m'
GOLDL=$'\033[38;2;245;208;97m'
GREY=$'\033[38;2;150;150;150m'
GREEN=$'\033[38;2;103;194;58m'
RED=$'\033[38;2;245;108;108m'
RST=$'\033[0m'

step() { printf "\n${GOLDL}==> %s${RST}\n" "$1"; }
ok()   { printf "  ${GREEN}OK${RST}  %s\n" "$1"; }
info() { printf "      ${GREY}%s${RST}\n" "$1"; }
warn() { printf "  ${RED}!!${RST}  %s\n" "$1"; }
die()  { printf "  ${RED}XX${RST}  %s\n" "$1" >&2; exit 1; }

# ---------------------------------------------------------------- 参数
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:-}"; shift 2 ;;
    --dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --bind) BIND_HOST="${2:-}"; shift 2 ;;
    --user) RUN_USER="${2:-}"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) die "未知参数：$1（用 --help 看用法）" ;;
  esac
done
DATA_DIR="$INSTALL_DIR/backend/data"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" != "0" ]; then die "请用 root 运行：sudo bash install.sh"; fi

# ---------------------------------------------------------------- 卸载
if [ "$UNINSTALL" = "1" ]; then
  step "卸载 $SERVICE_NAME"
  info "本操作只影响本面板，不会触碰 rt-panel 或任何其它服务。"
  printf "  确认卸载？数据目录 %s 将保留（如需彻底删除请手动 rm -rf）。[y/N] " "$DATA_DIR"
  read -r ans
  case "$ans" in
    y|Y) ;;
    *) die "已取消" ;;
  esac
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload || true
  ok "服务已停止并移除"
  info "程序目录：$INSTALL_DIR（未删除，如需删除：rm -rf $INSTALL_DIR）"
  info "数据目录：$DATA_DIR（未删除）"
  exit 0
fi

printf "\n${GOLD}  云枢MC开服面板 · Linux 安装${RST}\n"
printf "  ${GREY}安装目录 %s · 端口 %s · 服务名 %s${RST}\n" "$INSTALL_DIR" "$PORT" "$SERVICE_NAME"
printf "  ${GREY}独立部署：不依赖、不检测、不注册到同机其它面板${RST}\n"

# ---------------------------------------------------------------- 依赖
step "检查系统与依赖"
command -v systemctl >/dev/null 2>&1 || die "没有 systemctl（本脚本面向 systemd 发行版）"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || warn "apt-get update 失败，继续尝试安装"
  apt-get install -y -qq python3 python3-venv python3-pip curl tar ca-certificates >/dev/null 2>&1 \
    || warn "部分依赖安装失败，请自行确认 python3 / python3-venv 存在"
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q python3 python3-pip curl tar ca-certificates >/dev/null 2>&1 || warn "dnf 安装依赖失败"
elif command -v yum >/dev/null 2>&1; then
  yum install -y -q python3 python3-pip curl tar ca-certificates >/dev/null 2>&1 || warn "yum 安装依赖失败"
else
  warn "未识别的包管理器，请自行确保 python3 / python3-venv / curl / tar 可用"
fi
command -v python3 >/dev/null 2>&1 || die "找不到 python3"
ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"

# Java 不强制安装：面板能检测并用实例自带/系统 Java，也可在界面里一键下载 Adoptium
if command -v java >/dev/null 2>&1; then
  ok "检测到 Java：$(java -version 2>&1 | head -n1)"
else
  warn "未检测到 java —— 面板可以运行，但启动 MC 实例前需要装 Java，或在面板「设置 → Java 运行时」里下载"
fi

# ---------------------------------------------------------------- 用户
step "准备运行身份"
if [ "$RUN_USER" != "root" ] && ! id "$RUN_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$RUN_USER" 2>/dev/null || \
    useradd --system --home-dir "$INSTALL_DIR" --shell /sbin/nologin "$RUN_USER" 2>/dev/null || \
    warn "创建用户 $RUN_USER 失败，将沿用 root"
fi
ok "运行用户：$RUN_USER"

# ---------------------------------------------------------------- 复制程序
step "复制程序到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [ "$SRC_DIR" != "$INSTALL_DIR" ]; then
  # 只复制面板自己的东西；显式排除本机开发产物，避免把 .deps / 测试数据带上线
  tar -C "$SRC_DIR" \
      --exclude='./backend/.deps' --exclude='./backend/data' --exclude='./backend/tmp' \
      --exclude='./backend/__pycache__' --exclude='*/__pycache__' --exclude='./docs/ui-review/_probe' \
      -cf - . | tar -C "$INSTALL_DIR" -xf -
fi
chmod -R a+rX "$INSTALL_DIR"
ok "程序文件已就位"

# ---------------------------------------------------------------- 虚拟环境
step "创建虚拟环境并安装依赖"
cd "$INSTALL_DIR/backend"
if [ ! -x "$INSTALL_DIR/venv/bin/python" ]; then
  python3 -m venv "$INSTALL_DIR/venv" || die "创建 venv 失败（请确认已装 python3-venv）"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
"$INSTALL_DIR/venv/bin/pip" install --quiet -r requirements.txt || die "依赖安装失败（可试 --index-url https://pypi.org/simple）"
ok "Python 依赖已安装"

# ---------------------------------------------------------------- 配置
step "写入面板配置"
mkdir -p "$DATA_DIR"
if [ ! -f "$DATA_DIR/config.json" ]; then
  cat > "$DATA_DIR/config.json" <<JSON
{
  "port": ${PORT},
  "bind_host": "${BIND_HOST}",
  "site_name": "云枢MC开服面板",
  "session_hours": 24,
  "max_login_fails": 5,
  "lock_minutes": 10,
  "sample_interval": 5,
  "log_ring_lines": 2000,
  "download_workers": 2,
  "default_java": "",
  "default_jvm_args": "-XX:+UseG1GC -XX:MaxGCPauseMillis=200",
  "default_memory_mb": 2048,
  "backup_keep": 5,
  "mirror_prefix": "",
  "rcon_enabled": false,
  "rcon_host": "127.0.0.1",
  "rcon_port": 25575,
  "rcon_password": "",
  "curseforge_api_key": "",
  "auto_restart_limit": 3,
  "theme": "darkgold"
}
JSON
  ok "已写入 $DATA_DIR/config.json（端口 $PORT）"
else
  ok "已存在 $DATA_DIR/config.json，保留不动"
fi
chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR" 2>/dev/null || warn "chown 失败，权限可能需手动调整"
chmod 700 "$DATA_DIR" 2>/dev/null || true

# ---------------------------------------------------------------- systemd
step "注册 systemd 服务 $SERVICE_NAME"
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<UNIT
[Unit]
Description=MC Server Panel (Minecraft server control panel)
Documentation=file://$INSTALL_DIR/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR/backend
Environment=PYTHONUTF8=1
Environment=PYTHONIOENCODING=utf-8
Environment=MC_DATA_DIR=$DATA_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/backend/run.py
Restart=on-failure
RestartSec=5
# 面板需要管理 MC 进程与端口，放宽一点限制但仍保留基本隔离
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
ok "服务已注册（未启动，先初始化账号）"

# ---------------------------------------------------------------- 初始化 + 初始口令
step "初始化数据库并创建超级管理员"
info "初始口令只在本终端打印一次；不写入任何日志文件、不显示在网页、不落盘明文。"
INIT_OUT="$(cd "$INSTALL_DIR/backend" && PYTHONUTF8=1 MC_DATA_DIR="$DATA_DIR" \
  "$INSTALL_DIR/venv/bin/python" - <<'PY' 2>&1
import sys, os
sys.path.insert(0, os.getcwd())
from app.database import init_db
from app.auth import ensure_admin_user
init_db()
pwd = ensure_admin_user()
if pwd:
    sys.stderr.write('INITIAL_PASSWORD=' + pwd + '\n')
else:
    sys.stderr.write('INITIAL_PASSWORD=\n')
PY
)" || true
INIT_PW="$(printf '%s' "$INIT_OUT" | sed -n 's/^INITIAL_PASSWORD=//p' | head -n1)"

step "启动服务"
systemctl enable --now "$SERVICE_NAME" >/dev/null 2>&1 || warn "启动失败，请查看：journalctl -u $SERVICE_NAME -n 50"
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
  ok "服务已启动并设为开机自启"
else
  warn "服务未处于 active 状态，请查看：journalctl -u $SERVICE_NAME -n 80"
fi

# 防火墙（可选，失败不影响安装）
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" >/dev/null 2>&1 && ok "已放行 ufw 端口 $PORT/tcp" || true
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null 2>&1 && firewall-cmd --reload >/dev/null 2>&1 \
    && ok "已放行 firewalld 端口 $PORT/tcp" || true
fi

printf "\n${GOLD}================= 安装完成 =================${RST}\n"
printf "  面板地址   : ${GOLDL}http://<服务器IP>:%s/${RST}\n" "$PORT"
printf "  服务管理   : systemctl {status|restart|stop} %s\n" "$SERVICE_NAME"
printf "  查看日志   : journalctl -u %s -f\n" "$SERVICE_NAME"
printf "  数据目录   : %s\n" "$DATA_DIR"
printf "  程序目录   : %s\n" "$INSTALL_DIR"
printf "  配置文件   : %s/config.json（改端口后 restart 生效）\n" "$DATA_DIR"
printf "  卸载       : sudo bash %s/install.sh --uninstall\n" "$INSTALL_DIR"
printf "\n"
printf "  默认账号是 ${GOLDL}超级管理员${RST}，用户名 ${GOLDL}admin${RST}\n"
if [ -n "$INIT_PW" ]; then
  printf "  ${GOLD}初始口令（只显示这一次，请立刻保存）：${RST} ${GOLDL}%s${RST}\n" "$INIT_PW"
  printf "  ${GREY}提示：登录后请在「设置 → 修改口令」里更换。${RST}\n"
else
  printf "  ${GREY}数据库已存在管理员账号，未生成新口令（用原口令登录；忘记可执行 install.sh 之外的本地重置脚本）。${RST}\n"
fi
printf "  ${GREY}与 RT面板（rt-panel）零耦合：本脚本未读取、未修改、未注册到它的任何文件/服务/数据库。${RST}\n"
printf "${GOLD}============================================${RST}\n\n"

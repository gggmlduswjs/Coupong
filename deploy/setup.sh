#!/bin/bash
# ============================================
# Coupong Dashboard - Oracle Cloud 서버 셋업
# Ubuntu 22.04 ARM64 (Ampere A1)
# ============================================
set -e

echo "=========================================="
echo " Coupong 서버 초기 설정"
echo "=========================================="

# 1. 시스템 업데이트
echo "[1/6] 시스템 업데이트..."
sudo apt update && sudo apt upgrade -y

# 2. Python 3.11 + pip + git
echo "[2/6] Python 설치..."
sudo apt install -y python3.11 python3.11-venv python3-pip git

# 3. 프로젝트 클론
echo "[3/6] 프로젝트 클론..."
cd /home/ubuntu
if [ -d "Coupong" ]; then
    echo "  이미 존재 — pull"
    cd Coupong && git pull
else
    git clone https://github.com/gggmlduswjs/Coupong.git
    cd Coupong
fi

# 4. 가상환경 + 의존성
echo "[4/6] 가상환경 설정..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. systemd 서비스 등록
echo "[5/6] 서비스 등록..."
sudo cp deploy/coupong.service /etc/systemd/system/coupong.service
sudo systemctl daemon-reload
sudo systemctl enable coupong

# 6. 방화벽 포트 오픈
echo "[6/6] 방화벽 설정..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8503 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true

echo ""
echo "=========================================="
echo " 설정 완료!"
echo "=========================================="
echo ""
echo "다음 단계:"
echo "  1. .env 파일 생성:  nano /home/ubuntu/Coupong/.env"
echo "  2. 서비스 시작:     sudo systemctl start coupong"
echo "  3. 로그 확인:       sudo journalctl -u coupong -f"
echo "  4. 서버 IP 확인:    curl -s ifconfig.me"
echo ""
echo "이 IP를 쿠팡 WING API 화이트리스트에 추가하세요!"

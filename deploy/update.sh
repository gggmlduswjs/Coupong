#!/bin/bash
# Coupong 업데이트 스크립트 (코드 변경 후 실행)
set -e

cd /home/ubuntu/Coupong

echo "코드 업데이트 중..."
git pull origin main

echo "의존성 업데이트..."
source venv/bin/activate
pip install -r requirements.txt --quiet

echo "서비스 재시작..."
sudo systemctl restart coupong

echo "완료! 상태:"
sudo systemctl status coupong --no-pager

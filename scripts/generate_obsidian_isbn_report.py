"""ISBN 없는 상품 목록 Obsidian 문서 생성"""
import csv
import re
import sys
import io
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

# UTF-8 출력
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# CSV 읽기
with open('isbn_missing_products.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    products = list(reader)

print(f"총 {len(products)}개 상품 처리 중...")

# 계정별 분류
by_account = defaultdict(list)
for p in products:
    by_account[p['account_name']].append(p)

# 패턴 분류 함수
def classify_pattern(name):
    patterns = []
    if re.search(r'[+&]|세트|전\s*\d+권', name):
        patterns.append('묶음/세트')
    if '100발' in name or '100중' in name:
        patterns.append('100발100중')
    if '수능특강' in name:
        patterns.append('수능특강')
    if '개념' in name and '유형' in name:
        patterns.append('개념+유형')
    if '쎈' in name:
        patterns.append('쎈')
    if '자이스토리' in name or 'Xistory' in name:
        patterns.append('자이스토리')
    if '마더텅' in name:
        patterns.append('마더텅')
    if '완자' in name:
        patterns.append('완자')
    if '한끝' in name:
        patterns.append('한끝')
    if '오투' in name:
        patterns.append('오투')
    if '풍산자' in name:
        patterns.append('풍산자')
    if 'ITQ' in name.upper():
        patterns.append('ITQ')
    if 'DIAT' in name.upper():
        patterns.append('DIAT')
    if '컴퓨터활용능력' in name or '컴활' in name:
        patterns.append('컴퓨터활용능력')
    if re.search(r'기능사|산업기사|자격증', name):
        patterns.append('자격증')
    if re.search(r'Grammar|Reading|Level|Bricks|My (First|Next)', name):
        patterns.append('영어교재')
    if re.search(r'사은품|선물|증정|\*', name):
        patterns.append('사은품/선물')
    return patterns if patterns else ['기타']

# Obsidian 문서 생성
doc = f"""# ISBN 없는 상품 목록 (2026-02-11)

#isbn #missing-products #analysis

**생성일**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**총 상품 수**: {len(products):,}개

---

## 📊 전체 통계

### 패턴별 분류
"""

# 패턴별 카운트
pattern_count = defaultdict(int)
for p in products:
    for pattern in classify_pattern(p['product_name']):
        pattern_count[pattern] += 1

for pattern, count in sorted(pattern_count.items(), key=lambda x: x[1], reverse=True):
    pct = count / len(products) * 100
    doc += f'- **{pattern}**: {count:,}개 ({pct:.1f}%)\n'

doc += """
### 계정별 분포
"""

for account, items in sorted(by_account.items(), key=lambda x: len(x[1]), reverse=True):
    doc += f'- **{account}**: {len(items):,}개\n'

doc += """
---

## 📦 계정별 상세 목록

"""

for account, items in sorted(by_account.items()):
    doc += f"""
### {account} ({len(items):,}개)

"""

    # 패턴별로 그룹화
    by_pattern = defaultdict(list)
    for item in items:
        patterns = classify_pattern(item['product_name'])
        for pattern in patterns:
            by_pattern[pattern].append(item)

    for pattern in sorted(by_pattern.keys()):
        pitems = by_pattern[pattern]
        doc += f"""#### {pattern} ({len(pitems)}개)

"""
        # 전체 상품 표시 (제한 없음)
        for item in pitems:
            listing_id = item['listing_id']
            product_name = item['product_name']
            doc += f"- `{listing_id}` {product_name}\n"

        doc += '\n'

doc += """
---

## 🔍 주요 패턴 분석

### 1. 묶음/세트 상품 (약 30%)
- 단일 ISBN 할당 불가능
- 예: "쎈 + 라이트쎈 세트", "전 2권"
- **해결 방안**: 쉼표 구분 복수 ISBN 지원 또는 수동 분리

### 2. 100발100중 시리즈 (약 10%)
- 출판사별 버전 (동아, YBM, 천재 등)
- Books 테이블에 출판사별 버전 미등록
- **해결 방안**: 출판사별 교재 크롤링 필요

### 3. 자격증 (ITQ, DIAT, 컴활 등) (약 9%)
- 일반 서점 유통 없음
- 알라딘 API 검색 불가
- **해결 방안**: 전문 유통 API 탐색 또는 수동 입력

### 4. 영어교재 (Grammar, Reading 등) (약 3%)
- 외국 교재로 ISBN이 다르거나 없음
- **해결 방안**: 별도 외국 교재 DB 구축

### 5. 사은품/선물 표기 (약 17%)
- 상품명 노이즈로 매칭 실패
- **해결 방안**: 상품명 정제 강화

---

## 💡 권장 조치사항

### 단기 (1-2주)
1. **사은품 표기 제거**: 상품명에서 "*", "사은품", "선물" 자동 제거
2. **수동 매핑**: 주요 시리즈 (100발100중 등) 출판사별 버전 매핑
3. **Books 테이블 업데이트**: 2026 신간 크롤링

### 중기 (1-3개월)
1. **묶음 상품 처리**: 복수 ISBN 지원 (쉼표 구분)
2. **자격증 DB 구축**: ITQ, DIAT 등 전문 자격증 정보
3. **영어교재 DB**: 외국 교재 ISBN 데이터베이스

### 장기 (3-6개월)
1. **자동 정제 파이프라인**: 상품명 노이즈 제거 자동화
2. **출판사 API 연동**: 주요 교재 출판사 직접 연동
3. **AI 매칭**: 제목 유사도 기반 AI ISBN 추천

---

**관련 문서**:
- [[ISBN 개선 프로젝트 최종 보고서]]
- [[2026-02-11 개발 로그]]

**생성 스크립트**: `generate_obsidian_isbn_report.py`
"""

# 파일 저장 (G: 우선, .env OBSIDIAN_VAULT_PATH)
def _get_vault_dir():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OBSIDIAN_VAULT_PATH="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return Path(val) / "10. project" / "Coupong" / "03-Technical"
    return ROOT / "obsidian_vault" / "10. project" / "Coupong" / "03-Technical"

_vault = _get_vault_dir()
_vault.mkdir(parents=True, exist_ok=True)
output_path = _vault / "ISBN-없는-상품-목록.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(doc)

print('✅ Obsidian 문서 생성 완료')
print(f'   파일: {output_path}')
print(f'   총 {len(products):,}개 상품 정리')
print()
print('패턴별 통계:')
for pattern, count in sorted(pattern_count.items(), key=lambda x: x[1], reverse=True):
    pct = count / len(products) * 100
    print(f'  {pattern}: {count:,}개 ({pct:.1f}%)')

# Claude + Obsidian 통합 가이드

#obsidian #claude #integration

---

## 🎯 통합 목표

Claude Code에서 개발 → Obsidian에 자동 기록 → Claude로 분석 → 다시 개발

---

## 🔄 워크플로우

```
┌─────────────────┐
│  Claude Code    │ 개발 + 코딩
│  (여기)         │
└────────┬────────┘
         │ obsidian_logger.py
         │ (자동 로깅)
         ↓
┌─────────────────┐
│  Obsidian       │ 문서화 + 정리
│  (Vault)        │
└────────┬────────┘
         │ Text Generator
         │ (Claude API)
         ↓
┌─────────────────┐
│  Claude         │ 분석 + 개선
│  (in Obsidian)  │
└────────┬────────┘
         │ 피드백
         │
         ↓
     다시 개발
```

---

## 📦 필요한 것

### 1. 이미 있는 것 ✅
- Claude Code
- Obsidian Vault
- obsidian_logger.py

### 2. 추가로 설치할 것
- Obsidian (앱)
- Text Generator 플러그인
- Claude API Key

---

## 🚀 빠른 시작

### 1단계: Obsidian 설치
```
https://obsidian.md/download
→ 다운로드 및 설치
→ "Open folder as vault" 선택
→ C:\Users\MSI\Desktop\Coupong\obsidian_vault
```

### 2단계: Text Generator 설치
```
Obsidian 실행
→ Settings (Ctrl+,)
→ Community plugins
→ Browse
→ "Text Generator" 검색
→ Install → Enable
```

### 3단계: API Key 설정
```
https://console.anthropic.com/
→ API Keys
→ Create Key
→ 복사

Obsidian Settings
→ Text Generator
→ Provider: Anthropic
→ API Key: [붙여넣기]
→ Model: claude-sonnet-4-5
```

### 4단계: 테스트
```
1. Obsidian에서 텍스트 선택
2. Ctrl + J
3. "Explain this" 입력
4. Claude 응답 확인
```

---

## 💡 사용 예시

### 예시 1: 코드 설명

**작성한 노트:**
```markdown
# 마진 계산기

def calculate_margin(price, rate):
    return price * (0.801 - rate) - 2000
```

**Claude에게 질문:**
```
텍스트 선택 → Ctrl+J
"이 코드를 설명하고 예시를 들어줘"
```

**Claude 응답:**
```markdown
이 함수는 도서 판매의 순마진을 계산합니다.

## 계산 공식
- 0.801 = 판매가(0.9) - 쿠팡수수료(0.099)
- rate = 출판사 공급률
- 2000 = 배송비

## 예시
calculate_margin(15000, 0.35)
→ (15000 * 0.451) - 2000
→ 4,765원
```

### 예시 2: 문서 개선

**초안:**
```markdown
오늘 마진 계산기 만들었다.
버그도 고쳤다.
```

**Claude로 개선:**
```
선택 → Ctrl+J
"전문적인 개발 로그로 다시 작성"
```

**결과:**
```markdown
## 마진 계산기 구현 완료

### 구현 내용
- Publisher 모델에 calculate_margin() 메서드 추가
- 도서정가제 준수 (정가 × 0.9)
- 배송비 고려한 순마진 계산

### 버그 수정
- ZeroDivisionError 처리 추가
- 테스트 케이스 작성
```

### 예시 3: 주간 요약

**입력:**
```markdown
# 주간 요약 요청

<Text Generator>
다음 일일 노트들을 분석하고 주간 리포트 작성:
- [[2026-02-01]]
- [[2026-02-02]]
- [[2026-02-03]]
- [[2026-02-04]]
- [[2026-02-05]]

포함할 것:
- 주요 성과
- 완료된 기능
- 해결한 버그
- 다음 주 계획
</Text Generator>
```

**Claude 생성:**
```markdown
# 2월 1주차 개발 리포트

## 주요 성과 🎯
- Database V2 스키마 완성 (8개 테이블)
- 연도 추출 기능 구현 (87% 성공률)
- 마진 계산기 구현
- 묶음 SKU 생성기 구현

## 완료된 기능 ✅
1. 출판사 관리 시스템 (24개)
2. 자동 마진 계산
3. 배송 정책 자동 판단
4. 중복 방지 제약조건

## 해결한 버그 🐛
- 연도 추출 2자리 오류 수정
- ZeroDivisionError 처리 추가

## 다음 주 계획 📅
- 판매 분석 엔진 시작
- Streamlit 대시보드 프로토타입
- 자동 업로드 연구
```

---

## 🎨 고급 기능

### 프롬프트 템플릿

**templates/code-review.md**
```markdown
Review this code:

{{selection}}

분석할 것:
1. 버그 가능성
2. 성능 이슈
3. 보안 취약점
4. 가독성
5. 개선 제안
6. 테스트 케이스 제안
```

**사용법:**
```
코드 선택
→ Ctrl+J
→ "Use template: code-review"
```

### 단축키 설정

```
Settings → Hotkeys → Text Generator

추천 단축키:
- Ctrl+J: Generate
- Ctrl+Shift+J: Chat
- Alt+J: Repeat last
- Ctrl+K: Explain
- Ctrl+L: Improve
```

---

## 💰 비용

### Claude API
```
Sonnet 4.5:
- Input: $3/1M tokens
- Output: $15/1M tokens

예상:
- 일일 50개 요청: ~$0.50
- 월 비용: ~$15
```

### 무료 대안
```
1. Claude.ai 무료 플랜
   - 제한적이지만 무료
   - Copy/Paste 필요

2. Claude Code만 사용
   - 이미 사용 중
   - Obsidian은 기록용만
```

---

## 🔗 관련 노트

- [[Index]] - 메인 대시보드
- [[Development Timeline]] - 개발 타임라인
- [[OBSIDIAN_GUIDE]] - Obsidian 사용 가이드

---

## 📚 추가 자료

- OBSIDIAN_CLAUDE_INTEGRATION.md - 상세 가이드
- example_with_obsidian_logging.py - 로깅 예시
- obsidian_logger.py - 로거 소스

---

**완벽한 통합: Claude Code ↔️ Obsidian ↔️ Claude API** 🔄

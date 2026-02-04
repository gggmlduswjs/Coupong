# Obsidian에서 Claude 사용하기

## 🎯 통합 방법 (4가지)

### 방법 1: Text Generator Plugin (추천) ⭐
### 방법 2: Copilot Plugin
### 방법 3: Smart Connections
### 방법 4: Claude Code (현재 사용 중)

---

## 🚀 방법 1: Text Generator Plugin (추천)

가장 강력하고 사용하기 쉬운 방법

### 설치

1. **Obsidian 설정 열기**
   - `Ctrl + ,` (설정)
   - Community plugins 클릭
   - "Browse" 클릭

2. **Text Generator 검색 및 설치**
   - "Text Generator" 검색
   - Install 클릭
   - Enable 클릭

3. **Claude API Key 설정**
   ```
   Settings → Text Generator
   → Provider: Anthropic (Claude)
   → API Key: [여기에 입력]
   → Model: claude-opus-4-5
   ```

### API Key 발급

```
https://console.anthropic.com/
→ API Keys
→ Create Key
→ 복사
```

### 사용법

#### 1. 선택 텍스트로 작업
```
1. 텍스트 선택
2. Ctrl + J (단축키)
3. 프롬프트 입력
4. Claude가 응답 생성
```

#### 2. 템플릿 사용
```markdown
---
Text Generator Template
---

# 코드 리뷰 요청

다음 코드를 리뷰해주세요:

{{selection}}

체크할 것:
- 버그
- 성능
- 가독성
- 보안
```

#### 3. 커스텀 명령어
```
Settings → Text Generator → Commands

명령어 추가:
- "Summarize" → 요약
- "Explain" → 설명
- "Improve" → 개선
- "Translate to English" → 영어 번역
```

### 실전 예시

#### 코드 설명
```markdown
# 마진 계산 함수

<선택>
def calculate_margin(list_price, supply_rate):
    sale_price = list_price * 0.9
    supply_cost = list_price * supply_rate
    coupang_fee = sale_price * 0.11
    return sale_price - supply_cost - coupang_fee
</선택>

Ctrl + J → "Explain this code"

→ Claude가 설명 생성
```

#### 문서 개선
```markdown
# 구현 노트

<선택>
마진 계산기를 만들었다.
출판사별로 다르게 계산한다.
</선택>

Ctrl + J → "Make this more professional"

→ Claude가 전문적으로 재작성
```

---

## 🔧 방법 2: Copilot Plugin

AI 어시스턴트처럼 사용

### 설치

```
Settings → Community plugins
→ Browse → "Copilot"
→ Install → Enable
```

### 설정

```
Settings → Copilot
→ Provider: Anthropic
→ API Key: [입력]
→ Model: claude-sonnet-4-5
```

### 사용법

#### Chat 모드
```
Ctrl + P → "Copilot: Chat"

→ 채팅창 열림
→ Claude와 대화
```

#### 선택 텍스트 처리
```
1. 텍스트 선택
2. 우클릭 → "Copilot: Fix grammar"
3. 또는 "Copilot: Summarize"
```

#### 커스텀 프롬프트
```yaml
# .obsidian/copilot-prompts.md

## Code Review
Review this code for bugs and improvements:
{{selection}}

## Explain
Explain this in simple terms:
{{selection}}
```

---

## 🧠 방법 3: Smart Connections

노트 간 AI 기반 연결

### 설치

```
Community plugins
→ "Smart Connections"
→ Install → Enable
```

### 설정

```
Settings → Smart Connections
→ Enable Claude API
→ API Key: [입력]
```

### 기능

#### 1. 관련 노트 찾기
```
현재 노트를 읽고
→ 관련있는 다른 노트 자동 추천
→ Claude가 연결 관계 분석
```

#### 2. 질문하기
```
"이 프로젝트의 DB 스키마는?"
→ 관련 노트들을 찾아서
→ Claude가 종합 답변
```

#### 3. 자동 태그
```
노트 작성 후
→ Smart Connections 실행
→ Claude가 적절한 태그 추천
```

---

## 💻 방법 4: Claude Code (현재 방식) ⭐⭐⭐

**가장 강력한 방법!**

### 현재 구현된 시스템

```python
# obsidian_logger.py 사용

from obsidian_logger import ObsidianLogger

logger = ObsidianLogger()

# Claude Code에서 개발하면서
# 자동으로 Obsidian에 기록
logger.log_feature("기능명", "설명")
logger.log_decision("결정", "배경", "선택")
logger.log_bug("버그", "설명", "해결")
```

### 워크플로우

```
Claude Code (개발)
    ↓ (자동 로깅)
Obsidian (문서화)
    ↓ (검토)
Claude in Obsidian (분석/개선)
    ↓
다시 개발
```

### 통합 예시

```markdown
# 2026-02-05 개발 로그

## 마진 계산기 구현 완료

[Claude Code에서 자동 생성된 내용]

---

## 📝 Claude에게 질문

<Text Generator 사용>
이 마진 계산 로직에서 개선할 점은?

→ Claude 응답:
1. 배송비를 상수가 아닌 파라미터로
2. 에러 핸들링 추가
3. 단위 테스트 추가
</Text Generator>
```

---

## 🎨 고급 활용

### 1. 템플릿과 Claude 결합

**templates/feature-with-claude.md**
```markdown
# {{title}}

## Claude 분석

<Copilot: Analyze>
이 기능의 요구사항:
{{요구사항}}

분석해줘:
- 기술적 복잡도
- 예상 작업 시간
- 필요한 스킬
- 리스크
</Copilot>

## 구현 계획

<Text Generator>
위 분석을 바탕으로 단계별 구현 계획 작성
</Text Generator>
```

### 2. 일일 회고에 Claude 활용

```markdown
# 오늘의 작업

- 마진 계산기 구현
- 버그 3개 수정
- 테스트 작성

## Claude 회고

<Copilot: Chat>
오늘 작업을 분석하고:
1. 잘한 점
2. 개선할 점
3. 내일 우선순위
를 제안해줘
</Copilot>
```

### 3. 자동 요약 생성

```markdown
# 주간 리포트

<Text Generator>
다음 일일 노트들을 요약해줘:
- [[2026-02-01]]
- [[2026-02-02]]
- [[2026-02-03]]
- [[2026-02-04]]
- [[2026-02-05]]

주요 성과, 이슈, 다음 주 계획 포함
</Text Generator>
```

### 4. 코드 리뷰 자동화

```markdown
# 코드 리뷰: 마진 계산기

```python
def calculate_margin(list_price, supply_rate):
    sale_price = list_price * 0.9
    supply_cost = list_price * supply_rate
    coupang_fee = sale_price * 0.11
    return sale_price - supply_cost - coupang_fee
```

<Text Generator: Code Review>
위 코드를 리뷰하고:
- 버그 가능성
- 성능 이슈
- 개선 제안
- 테스트 케이스 제안
</Text Generator>
```

---

## 🔥 실전 통합 워크플로우

### 아침: 계획 수립

```markdown
# 2026-02-06 계획

## 오늘 할 일 (초안)
- CSV 생성기 리팩토링
- 테스트 추가
- 문서 업데이트

<Copilot>
위 작업들의 우선순위를 정하고
예상 소요 시간과 함께
구체적인 계획을 세워줘
</Copilot>
```

### 개발 중: 실시간 지원

```python
# Python 코드 작성 (Claude Code)
# ↓ 자동 로깅
# Obsidian에 기록됨

# Obsidian에서 확인하며
# Text Generator로 개선점 질문
```

### 오후: 문서화

```markdown
# CSV 생성기 리팩토링

## 변경 사항
- 200줄 → 150줄
- 클래스 분리
- 테스트 추가

<Text Generator>
위 변경사항을 기술 문서 형식으로
작성해줘. 포함할 것:
- Before/After 비교
- 개선 효과
- 사용 예시
</Text Generator>
```

### 저녁: 회고

```markdown
# 일일 회고

## 완료 ✅
- CSV 생성기 리팩토링
- 테스트 커버리지 85%
- 문서 업데이트

## 어려웠던 점
- 기존 코드 의존성 복잡

<Copilot: Chat>
오늘 작업을 분석하고
내일 더 효율적으로 일하는 방법 제안
</Copilot>
```

---

## ⚙️ 추천 설정

### Text Generator 단축키
```
Ctrl + J: 선택 텍스트 처리
Ctrl + Shift + J: 새 채팅
Alt + J: 마지막 명령 반복
```

### Copilot 단축키
```
Ctrl + Shift + L: Chat 열기
Ctrl + Shift + K: 선택 텍스트 개선
```

### 프롬프트 라이브러리

**.obsidian/prompts/code-review.md**
```markdown
Review this code:

{{selection}}

Check for:
1. Bugs and edge cases
2. Performance issues
3. Security vulnerabilities
4. Code style and readability
5. Suggestions for improvement
```

**.obsidian/prompts/explain-simple.md**
```markdown
Explain this in simple terms:

{{selection}}

Use:
- Simple language
- Examples
- Analogies
```

**.obsidian/prompts/improve-writing.md**
```markdown
Improve this text:

{{selection}}

Make it:
- More professional
- Clear and concise
- Well-structured
- Error-free
```

---

## 💰 비용

### Claude API 가격
```
Claude Sonnet 4.5:
- Input: $3 / 1M tokens
- Output: $15 / 1M tokens

예상 비용:
- 일일 100개 요청: ~$1
- 월 비용: ~$30
```

### 무료 대안
```
1. Claude.ai 무료 플랜 사용 (제한적)
2. Copy/Paste 워크플로우
3. Claude Code만 사용 (이미 사용 중)
```

---

## 🎯 최적의 조합 (추천)

### 조합 1: 완전 자동화 ⭐⭐⭐
```
Claude Code (개발)
    ↓ obsidian_logger (자동)
Obsidian (기록)
    ↓ Text Generator (분석)
Claude (개선)
    ↓
다시 개발
```

### 조합 2: 비용 절감
```
Claude Code (개발)
    ↓ 자동 로깅
Obsidian (무료)
    ↓ 수동 복사
Claude.ai (무료 플랜)
```

### 조합 3: 최대 활용
```
모든 플러그인 설치
→ 상황별로 선택 사용
→ 개발: Claude Code
→ 분석: Text Generator
→ 채팅: Copilot
→ 연결: Smart Connections
```

---

## 📋 설치 체크리스트

```markdown
- [ ] Obsidian 설치
- [ ] Vault 열기 (obsidian_vault/)
- [ ] Text Generator 플러그인 설치
- [ ] Claude API Key 발급
- [ ] API Key 설정
- [ ] 단축키 설정
- [ ] 프롬프트 템플릿 생성
- [ ] 테스트 실행
```

---

## 🚀 다음 단계

1. **Text Generator 설치**
   ```
   Obsidian → Settings → Community plugins
   → Browse → "Text Generator" → Install
   ```

2. **API Key 설정**
   ```
   https://console.anthropic.com/
   → Create API Key
   → Copy to Text Generator settings
   ```

3. **테스트**
   ```
   1. 텍스트 선택
   2. Ctrl + J
   3. "Explain this"
   4. Claude 응답 확인
   ```

4. **통합**
   ```python
   # 개발하면서 자동 로깅
   from obsidian_logger import ObsidianLogger
   logger = ObsidianLogger()

   # Obsidian에서 Claude로 분석
   # Text Generator 사용
   ```

---

## 🎉 완성!

이제 다음이 가능합니다:

✅ **Claude Code** → 자동으로 Obsidian 기록
✅ **Obsidian** → Claude에게 분석 요청
✅ **Claude** → 개선 제안
✅ **다시 개발** → 자동 기록

**완벽한 순환 워크플로우! 🔄**

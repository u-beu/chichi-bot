# 브랜치 네이밍 규칙

## 배경

`chore/cors-middleware`, `refactor/api-routers`, `docs/redis-doc-sync`처럼 최근에는 `타입/설명` 패턴이 자리잡았지만, 초기에는 `issue7-webAPI/Playback`, `issue5-requestAPI`, `issue1`처럼 브랜치마다 형식이 달랐다. 앞으로 만드는 모든 브랜치는 아래 규칙을 따른다.

## 기본 형식

```
<type>/<description>
```

- `description`은 영어 소문자 kebab-case로 작성한다 (예: `chore/cors-middleware`).
- 연결된 GitHub 이슈가 없는 작업에만 이 형식을 쓴다.

## 이슈가 있는 작업 (필수)

작업에 대응하는 GitHub 이슈가 이미 생성되어 있다면, 이슈번호를 반드시 브랜치명에 포함한다.

```
<type>/<issue-number>-<description>
```

이슈번호는 `/` 바로 다음, `description` 앞에 하이픈으로 붙인다.

예: `feat/23-guild-queue-persist`, `fix/31-empty-queue-crash`

## 타입 목록

| 타입 | 용도 |
|---|---|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 동작 변화 없는 구조 개선 |
| `docs` | 문서만 변경 |
| `chore` | 빌드/설정/의존성 등 잡무성 변경 |
| `test` | 테스트 코드 추가/수정 |

## 규칙 준수 예시 (최근 브랜치)

| 브랜치명 | 타입 | 비고 |
|---|---|---|
| `chore/cors-middleware` | chore | 이슈 없음 |
| `refactor/api-routers` | refactor | 이슈 없음 |
| `refactor/music-cog` | refactor | 이슈 없음 |
| `docs/redis-doc-sync` | docs | 이슈 없음 |

## 레거시 네이밍 (사용 중단)

`issue7-webAPI/Playback`, `issue5-requestAPI`, `issue1`, `issue2` 형태는 과거에 쓰던 방식이며, 앞으로는 사용하지 않는다.

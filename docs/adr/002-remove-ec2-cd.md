# ADR 002: EC2 CD 제거 및 CI 전환 (test + 이미지 빌드 검증)

- **Status:** Accepted (승인됨)
- **Date:** 2026-10-27
- **Related:** Issue #48, branch `chore/48-remove-ec2-deploy`, 기존 워크플로 보관본 [`docs/archive/cicd-ec2.yml`](../archive/cicd-ec2.yml)

---

## 1. Context (배경 및 기존 구조)
`.github/workflows/cicd.yml`은 EC2 배포를 전제로 구성되어 있었다. GitHub Actions에서 이미지를 빌드해 DockerHub에 push하면, EC2가 이를 pull해 컨테이너를 재시작하는 방식이다. `workflow_dispatch`의 `env` 입력(`init`/`prod`/`config`)으로 배포 방식을 분기했다.

- **기존 흐름:** `test` ➔ `build` (DockerHub push) ➔ `deploy-init` (SCP `.env` + SSH `docker run`) / `deploy-config` (SCP `.env` + SSH 컨테이너 재시작)
- **사용 secrets:** `EC2_KEY`, `EC2_HOST`, `EC2_USER`, `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` 등

---

## 2. Decision Driver (결정 요인)
1. **배포 대상 변경:** 배포 환경이 EC2에서 로컬로 바뀌어 DockerHub push와 EC2 SCP/SSH 배포가 불필요해짐.
2. **아키텍처 단순화 (KISS 원칙):** 사용하지 않는 job과 `init`/`prod`/`config` 분기를 제거.
3. **보안 표면 축소:** 더 이상 쓰지 않는 SSH 키와 DockerHub 토큰을 secrets에서 제거할 수 있음.
4. **빌드 깨짐 조기 발견:** `Dockerfile`은 `apt` 패키지와 `requirements-${TARGET}.txt` 설치가 얽혀 있어 pytest로는 잡히지 않는 깨짐이 생길 수 있음. 특히 worker는 PyTorch/Librosa 설치 때문에 빌드가 무거움.

---

## 3. Options Considered (고려했던 대안들)

### Option A: CD 유지
- **장점:** 변경 없음.
- **단점:** 사용하지 않는 EC2/DockerHub 자격 증명과 job이 계속 남음.

### Option B: PR은 test, 수동 실행 시 bot/worker 이미지 빌드 검증 (선택)
- **장점:** CD 제거로 워크플로 단순화. PR마다 가벼운 test만 실행하고, 무거운 worker 빌드는 필요할 때만 실행.
- **단점:** 빌드 검증이 수동이라 누락될 수 있음.

### Option C: 워크플로 전체 삭제
- **장점:** 관리 대상 최소화.
- **단점:** PR 단위 자동 테스트와 빌드 검증 수단을 모두 잃음.

---

## 4. Decision (최종 결정)
**Option B 선택.**
- `deploy-init`, `deploy-config` job과 DockerHub push, `inputs.env`를 제거한다.
- `cicd.yml`을 `ci.yml`로 이름을 바꾸고 `pull_request`(main 대상) 시 `test`만 실행한다.
- `workflow_dispatch`의 `build` 입력을 선택하면 `TARGET`(bot, worker) 매트릭스로 이미지를 빌드해 검증한다.
- 기존 워크플로는 `docs/archive/cicd-ec2.yml`로 보관한다.

---

## 5. Consequences (결과 및 영향)

### Positive (개선된 점)
- **워크플로 단순화:** 배포 분기와 중복된 EC2 단계(init/config) 제거.
- **외부 자격 증명 의존 제거:** EC2 SSH 키와 DockerHub 토큰이 CI에 더 이상 필요 없음.
- **빌드 범위 확대:** 기존 `build`는 `TARGET` 기본값(`bot`)만 빌드했으나, bot/worker 둘 다 검증.

### Negative & Risks (향후 주의사항 및 리스크)
- **빌드 검증 누락 가능성:** 수동 실행이라 `Dockerfile`/`requirements-*.txt` 변경 PR에서 실행을 잊을 수 있음. 필요해지면 `pull_request`에 `paths` 필터를 걸어 자동화.
- **로컬 배포 시 직접 빌드 필요:** CI는 이미지를 어디에도 push하지 않으므로 배포용 이미지는 로컬에서 빌드해야 함.

### 후속 조치
- GitHub secrets `EC2_KEY`, `EC2_HOST`, `EC2_USER`, `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`을 수동으로 삭제한다. (`TODO.md` 참조)

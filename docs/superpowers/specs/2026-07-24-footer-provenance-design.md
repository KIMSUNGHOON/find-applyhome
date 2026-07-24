# Footer Provenance Design

## Goal

페이지 하단에서 데이터 출처, 공개 저장소, 개발자를 명확히 확인할 수 있게 한다. 기존 결과 화면보다
시각적으로 앞서지 않으며, 이메일이나 배포·저장소 내부 정보는 노출하지 않는다.

## Content

기존 footer의 참고 문구를 다음 세 가지 공개 정보로 확장한다.

- **데이터 출처:** 청약홈 「분양권 정보(전매제한 등)」
  - 링크: `https://www.applyhome.co.kr/rs/rsa/selectResaleListView.do`
  - 공개 데이터를 조회하며 참고용이라는 기존 안내를 유지한다.
- **저장소:** `KIMSUNGHOON/find-applyhome`
  - 링크: `https://github.com/KIMSUNGHOON/find-applyhome`
- **개발자:** `Seonghun Kim · @KIMSUNGHOON`
  - 링크: `https://github.com/KIMSUNGHOON`
  - 이메일은 표시하지 않는다.

표시 문구는 구현 세부사항이나 Redis·Vercel 정보를 설명하지 않는다. 청약홈의 공식 서비스라는 인상을
주지 않으며, 데이터 해석에 대한 기존 참고용 고지를 유지한다.

## Layout and Visual Treatment

기존 footer의 상단 hairline, 어두운 배경, 작은 `caption` 계층을 그대로 사용한다. 별도 About band,
카드, 배지, 아이콘, 애니메이션은 추가하지 않는다.

- 첫 줄은 데이터 출처와 참고용 고지다.
- 둘째 줄은 저장소와 개발자 링크를 나란히 둔다.
- 링크는 기존 `--on-dark`와 hairline 계열을 사용하고, underline 또는 현재 footer에 맞는 절제된
  텍스트 처리를 사용한다.
- 좁은 화면에서는 두 줄의 항목이 자연스럽게 줄바꿈되며 가로 스크롤을 만들지 않는다.
- 기존 M 삼색 스트라이프와 세대 grid가 계속 화면의 유일한 시각적 서명으로 남는다.

## Accessibility and Link Safety

- 링크 텍스트만으로 목적지를 이해할 수 있어야 한다.
- 키보드 기본 focus 표시를 제거하지 않는다.
- 외부 링크는 새 창으로 열고 `target="_blank"`와 `rel="noopener noreferrer"`를 함께 사용한다.
- 장식용 아이콘이나 색만으로 링크 의미를 전달하지 않는다.

## Files and Boundaries

- 수정: `public/index.html`
- 추가 테스트: `tests/test_frontend_cache.mjs`
- 필요하면 README의 테스트 수만 실제 최종 결과로 갱신한다.

캐시 API, freshness 정책, Redis schema, 검색·스캔·CSV 동작은 변경하지 않는다.

## Verification

- HTML 계약 테스트로 출처·저장소·개발자 문구와 정확한 URL을 확인한다.
- 세 외부 링크 모두 `target`과 `rel` 보안 속성을 갖는지 확인한다.
- footer가 기존 caption 계층과 모바일 줄바꿈 구조를 사용하는지 확인한다.
- inline module과 `public/cache.mjs` 문법, 전체 Node/Python 회귀 테스트, 비밀정보 scan을 다시 실행한다.
- Vercel Preview가 SSO 보호 상태라 자동 렌더 확인이 불가능하면 그 제약을 최종 보고서에 명시한다.

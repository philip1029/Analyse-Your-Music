// 백엔드 주소. 같은 컴퓨터에서 열면 localhost, 폰처럼 다른 기기에서 컴퓨터의 IP(예: 192.168.0.5:5173)로 열면
// 그 컴퓨터의 IP 의 8000 번 포트로 자동으로 맞춘다. VITE_API_URL 환경변수로 직접 지정할 수도 있다.
const fromEnv = import.meta.env.VITE_API_URL as string | undefined;
export const BASE_URL = fromEnv ?? `${window.location.protocol}//${window.location.hostname}:8000`;

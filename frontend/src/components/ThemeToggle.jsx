import { useCallback, useEffect, useState } from 'react';

/**
 * 다크/라이트 전환.
 *
 * 상태는 셋이다 — 선택 없음(시스템 설정을 따름) / light / dark.
 * 버튼은 "지금 보이는 것의 반대"로 넘기고, 그 선택을 localStorage 에 남긴다.
 * 저장된 값은 index.html 의 인라인 스크립트가 첫 페인트 전에 이미 적용해 둔다.
 * 여기서는 이후의 변경만 반영한다.
 */
const STORAGE_KEY = 'theme';

function readStored() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null;
  }
}

function systemTheme() {
  return typeof window !== 'undefined'
    && window.matchMedia('(prefers-color-scheme: light)').matches
    ? 'light'
    : 'dark';
}

export default function ThemeToggle() {
  const [choice, setChoice] = useState(readStored);
  const [system, setSystem] = useState(systemTheme);
  const effective = choice ?? system;

  // 선택하지 않은 상태에서 OS 설정이 바뀌면 따라간다.
  useEffect(() => {
    const mql = window.matchMedia('(prefers-color-scheme: light)');
    const onChange = (e) => setSystem(e.matches ? 'light' : 'dark');
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (choice) root.setAttribute('data-theme', choice);
    else root.removeAttribute('data-theme');

    try {
      if (choice) localStorage.setItem(STORAGE_KEY, choice);
      else localStorage.removeItem(STORAGE_KEY);
    } catch { /* 저장소가 막혀 있어도 화면 전환은 동작한다 */ }
  }, [choice]);

  const toggle = useCallback(() => {
    setChoice(effective === 'dark' ? 'light' : 'dark');
  }, [effective]);

  const next = effective === 'dark' ? 'light' : 'dark';

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      {effective === 'dark' ? (
        // 달 — 지금 다크이므로 라이트로 넘어갈 수 있음을 태양으로 보여줘도 되지만,
        // 현재 상태를 표시하는 편이 오해가 적다.
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      )}
    </button>
  );
}

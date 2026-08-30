import { BrowserRouter, Routes, Route, Link, NavLink } from 'react-router-dom';
import './index.css';
import Home from './pages/Home';
import Docs from './pages/Docs';

// NavLink 는 현재 경로와 일치하면 isActive 를 넘겨준다.
// 링크가 하나뿐이면 활성 표시가 의미를 갖지 못하므로 두 경로를 모두 노출한다.
const navClass = ({ isActive }) => (isActive ? 'nav-link is-active' : 'nav-link');

function App() {
  return (
    <BrowserRouter>
      <div className="ambient-orb ambient-orb-top"></div>
      <div className="ambient-orb ambient-orb-bottom"></div>

      <header className="header">
        <div className="container flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="pulse-dot"></div>
            <Link to="/" className="brand font-bold text-lg tracking-tight">
              TechDoc Agent
            </Link>
          </div>
          <nav className="flex gap-6">
            <NavLink to="/" end className={navClass}>
              Ask
            </NavLink>
            <NavLink to="/docs" className={navClass}>
              Documents
            </NavLink>
          </nav>
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/docs" element={<Docs />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

export default App;

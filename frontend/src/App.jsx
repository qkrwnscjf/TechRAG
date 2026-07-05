import React from 'react';
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import './index.css';
import Home from './pages/Home';
import Docs from './pages/Docs';

function App() {
  return (
    <BrowserRouter>
      <div className="ambient-orb ambient-orb-top"></div>
      <div className="ambient-orb ambient-orb-bottom"></div>

      <header className="header">
        <div className="container flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="pulse-dot"></div>
            <Link to="/" className="font-bold text-lg tracking-tight text-foreground" style={{ textDecoration: 'none' }}>
              TechDoc Agent
            </Link>
          </div>
          <nav className="flex gap-4">
            <Link to="/docs" className="text-muted hover:text-foreground text-sm font-medium transition-colors" style={{ textDecoration: 'none' }}>
              Docs
            </Link>
            <a href="#" className="text-muted hover:text-foreground text-sm font-medium transition-colors" style={{ textDecoration: 'none' }}>
              Settings
            </a>
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

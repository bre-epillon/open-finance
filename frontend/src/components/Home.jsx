import React from 'react';
import { Link } from 'react-router-dom';
import { Briefcase, Activity } from 'lucide-react';
import './Home.css';

export default function Home() {
  return (
    <div className="home-container animate-fade-in">
      <div className="home-header">
        <h1 className="home-title">LiteFi</h1>
        <p className="home-subtitle">Portfolio analytics over your own price history.</p>
      </div>

      <div className="home-grid">
        <Link to="/portfolio" className="home-card glass panel">
          <div className="home-card-icon-wrapper">
            <Briefcase size={28} className="home-card-icon" style={{ color: 'var(--series-1)' }} />
          </div>
          <h2 className="home-card-title">Portfolio</h2>
          <p className="home-card-desc">
            Allocation, performance against a benchmark, drawdown and risk, holdings
            ledger, and cash-flow history.
          </p>
        </Link>

        <Link to="/terminal" className="home-card glass panel">
          <div className="home-card-icon-wrapper">
            <Activity size={28} className="home-card-icon" style={{ color: 'var(--series-2)' }} />
          </div>
          <h2 className="home-card-title">Research</h2>
          <p className="home-card-desc">
            Overlay historical price curves for any tracked asset, and backfill a new
            ticker into QuestDB.
          </p>
        </Link>
      </div>
    </div>
  );
}

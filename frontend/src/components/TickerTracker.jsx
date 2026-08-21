import React, { useState } from 'react';
import { Plus, Loader2, Sparkles } from 'lucide-react';
import './TickerTracker.css';

/**
 * Registers a new ticker and kicks off its historical backfill.
 */
export default function TickerTracker({ onTrackSuccess, apiBase }) {
  const [newTicker, setNewTicker] = useState('');
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState({ type: '', message: '' });

  const handleTrackSubmit = async (e) => {
    e.preventDefault();
    const tickerToTrack = newTicker.trim().toUpperCase();
    if (!tickerToTrack) return;

    setLoading(true);
    setFeedback({ type: '', message: '' });

    try {
      const response = await fetch(`${apiBase}/track?ticker=${tickerToTrack}`, {
        method: 'POST',
      });
      const data = await response.json();

      if (response.status === 200) {
        if (data.status === 'already_tracked') {
          setFeedback({
            type: 'info',
            message: `"${tickerToTrack}" is already tracked.`
          });
        } else {
          setFeedback({
            type: 'success',
            message: `Backfilling "${tickerToTrack}" now -- it will appear above shortly.`
          });
          setNewTicker('');
          // Refresh parent tracked list
          await onTrackSuccess(tickerToTrack);
        }
      } else {
        setFeedback({
          type: 'error',
          message: data.detail || `Could not resolve "${tickerToTrack}".`
        });
      }
    } catch (err) {
      console.error('Error tracking ticker:', err);
      setFeedback({
        type: 'error',
        message: 'Network error. Please try again.'
      });
    } finally {
      setLoading(false);
      // Auto fade-out feedback after 4 seconds
      setTimeout(() => {
        setFeedback((prev) => (prev.message ? { type: '', message: '' } : prev));
      }, 4500);
    }
  };

  return (
    <div className="ticker-tracker-panel panel glass">
      <div className="panel-header">
        <h2 className="panel-title">
          <Sparkles size={16} className="title-icon-sparkle" />
          <span>Track a New Asset</span>
        </h2>
      </div>

      <p className="panel-desc">
        Backfill any Yahoo Finance ticker (e.g. TSLA, NVDA, ETH-USD) into QuestDB. History is fetched in the background.
      </p>

      <form onSubmit={handleTrackSubmit} className="tracker-form">
        <div className="input-wrapper">
          <input
            type="text"
            placeholder="e.g. NVDA, COIN"
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value)}
            disabled={loading}
            className="tracker-input"
          />
          <button type="submit" className="tracker-submit-btn" disabled={loading || !newTicker.trim()}>
            {loading ? <Loader2 size={16} className="spinner" /> : <Plus size={16} />}
          </button>
        </div>
      </form>

      {feedback.message && (
        <div className={`feedback-alert feedback-${feedback.type}`}>
          <span className="feedback-bullet" />
          <span className="feedback-text">{feedback.message}</span>
        </div>
      )}
    </div>
  );
}

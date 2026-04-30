import React, { useState } from 'react';
import './styles.css';

// ===== Types =====

export type SceneType = 'approval_reminder' | 'weekly_report' | 'quote_aggregation' | 'anomaly_detection' | 'entity_summary';
export type FeedbackType = 'thumbs_up' | 'thumbs_down' | 'refresh';

export interface SceneCardData {
  card_id: string;
  scene_type: SceneType;
  title: string;
  description: string;
  confidence: number;
  priority: number;
  action_label: string;
  action_data: Record<string, unknown>;
}

export interface SceneCardProps {
  card: SceneCardData;
  onFeedback: (cardId: string, feedback: FeedbackType) => Promise<void>;
  onAction: (cardId: string, actionLabel: string, actionData: Record<string, unknown>) => Promise<void>;
  onDismiss?: (cardId: string) => void;
}

// ===== Scene Icon =====

const SCENE_ICONS: Record<SceneType, string> = {
  approval_reminder: '📋',
  weekly_report: '📝',
  quote_aggregation: '💰',
  anomaly_detection: '🔍',
  entity_summary: '👤',
};

const SCENE_COLORS: Record<SceneType, string> = {
  approval_reminder: '#e8f5e9',
  weekly_report: '#e3f2fd',
  quote_aggregation: '#fff8e1',
  anomaly_detection: '#fce4ec',
  entity_summary: '#f3e5f5',
};

// ===== Scene Card Component =====

export const SceneCard: React.FC<SceneCardProps> = ({
  card,
  onFeedback,
  onAction,
  onDismiss,
}) => {
  const [loading, setLoading] = useState(false);
  const [feedbackGiven, setFeedbackGiven] = useState<FeedbackType | null>(null);
  const [dismissed, setDismissed] = useState(false);

  const handleFeedback = async (feedback: FeedbackType) => {
    setLoading(true);
    try {
      await onFeedback(card.card_id, feedback);
      setFeedbackGiven(feedback);

      // Auto-dismiss after thumbs down
      if (feedback === 'thumbs_down') {
        setTimeout(() => {
          setDismissed(true);
          onDismiss?.(card.card_id);
        }, 500);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async () => {
    setLoading(true);
    try {
      await onAction(card.card_id, card.action_label, card.action_data);
    } finally {
      setLoading(false);
    }
  };

  if (dismissed) return null;

  const icon = SCENE_ICONS[card.scene_type] || '📌';
  const bgColor = SCENE_COLORS[card.scene_type] || '#f5f5f5';

  return (
    <div className="scene-card" style={{ backgroundColor: bgColor }}>
      {/* Header */}
      <div className="scene-card-header">
        <span className="scene-icon">{icon}</span>
        <h4 className="scene-title">{card.title}</h4>
        {onDismiss && (
          <button className="btn-dismiss" onClick={() => { setDismissed(true); onDismiss(card.card_id); }}>
            ✕
          </button>
        )}
      </div>

      {/* Description */}
      <p className="scene-description">{card.description}</p>

      {/* Action button */}
      <div className="scene-actions">
        {card.action_label && (
          <button className="btn-scene-action" onClick={handleAction} disabled={loading}>
            {card.action_label}
          </button>
        )}
      </div>

      {/* Feedback buttons */}
      <div className="scene-feedback">
        {!feedbackGiven ? (
          <>
            <button
              className={`btn-feedback thumbs-up ${feedbackGiven === 'thumbs_up' ? 'active' : ''}`}
              onClick={() => handleFeedback('thumbs_up')}
              disabled={loading}
              title="有用"
            >
              👍
            </button>
            <button
              className={`btn-feedback thumbs-down ${feedbackGiven === 'thumbs_down' ? 'active' : ''}`}
              onClick={() => handleFeedback('thumbs_down')}
              disabled={loading}
              title="不需要"
            >
              👎
            </button>
            <button
              className="btn-feedback refresh"
              onClick={() => handleFeedback('refresh')}
              disabled={loading}
              title="换一个"
            >
              🔄
            </button>
          </>
        ) : (
          <span className="feedback-thanks">
            {feedbackGiven === 'thumbs_up' ? '👍 感谢反馈' :
             feedbackGiven === 'thumbs_down' ? '👎 已记录，7天内不再推荐' :
             '🔄 已降权'}
          </span>
        )}
      </div>

      {/* Confidence indicator */}
      <div className="scene-confidence" title={`置信度: ${(card.confidence * 100).toFixed(0)}%`}>
        <div
          className="confidence-bar"
          style={{ width: `${card.confidence * 100}%` }}
        />
      </div>
    </div>
  );
};

// ===== Scene Card List =====

export interface SceneCardListProps {
  cards: SceneCardData[];
  onFeedback: (cardId: string, feedback: FeedbackType) => Promise<void>;
  onAction: (cardId: string, actionLabel: string, actionData: Record<string, unknown>) => Promise<void>;
  onDismiss?: (cardId: string) => void;
}

export const SceneCardList: React.FC<SceneCardListProps> = ({
  cards,
  onFeedback,
  onAction,
  onDismiss,
}) => {
  if (cards.length === 0) {
    return (
      <div className="scene-cards-empty">
        <p>暂无推荐</p>
        <p className="hint">MailKnow 会根据您的邮件使用习惯智能推荐场景</p>
      </div>
    );
  }

  return (
    <div className="scene-card-list">
      {cards.map((card) => (
        <SceneCard
          key={card.card_id}
          card={card}
          onFeedback={onFeedback}
          onAction={onAction}
          onDismiss={onDismiss}
        />
      ))}
    </div>
  );
};

export default SceneCard;

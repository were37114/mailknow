import React, { useState, useCallback } from 'react';
import './styles.css';

// ===== Types =====

export type ConfidenceLevel = 'high' | 'medium' | 'low';
export type AmountCategory = 'small' | 'medium' | 'large' | 'unknown';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'forwarded' | 'delegated' | 'deferred' | 'expired';

export interface ApprovalCardData {
  card_id: string;
  email_id: string;
  subject: string;
  requester: string;
  approver: string;
  confidence: number;
  confidence_level: ConfidenceLevel;
  amount: number | null;
  amount_category: AmountCategory;
  currency: string;
  deadline: string | null;
  status: ApprovalStatus;
  is_actionable: boolean;
  is_small_amount: boolean;
  is_large_amount: boolean;
  created_at: string;
  reason?: string;
}

export interface ApprovalCardProps {
  card: ApprovalCardData;
  onApprove: (cardId: string, comment?: string) => Promise<void>;
  onReject: (cardId: string, comment?: string) => Promise<void>;
  onForward: (cardId: string, forwardTo: string, comment?: string) => Promise<void>;
  onEmailClick?: (emailId: string) => void;
  compact?: boolean;
}

// ===== Confidence Badge =====

const ConfidenceBadge: React.FC<{ level: ConfidenceLevel; confidence: number }> = ({ level, confidence }) => {
  const config = {
    high: { label: '高置信', className: 'confidence-high', icon: '🟢' },
    medium: { label: '中置信', className: 'confidence-medium', icon: '🟡' },
    low: { label: '低置信', className: 'confidence-low', icon: '🔴' },
  };
  const { label, className, icon } = config[level];

  return (
    <span className={`confidence-badge ${className}`} title={`置信度: ${(confidence * 100).toFixed(0)}%`}>
      {icon} {label} {(confidence * 100).toFixed(0)}%
    </span>
  );
};

// ===== Amount Badge =====

const AmountBadge: React.FC<{ amount: number | null; category: AmountCategory; currency: string }> = ({ amount, category, currency }) => {
  if (amount === null) return null;

  const config = {
    small: { label: '小额', className: 'amount-small' },
    medium: { label: '中额', className: 'amount-medium' },
    large: { label: '大额', className: 'amount-large' },
    unknown: { label: '', className: '' },
  };
  const { label, className } = config[category];
  const currencySymbol = currency === 'CNY' || currency === 'RMB' ? '¥' : '$';
  const formattedAmount = amount >= 10000
    ? `${(amount / 10000).toFixed(1)}万`
    : amount.toLocaleString();

  return (
    <span className={`amount-badge ${className}`}>
      {label} {currencySymbol}{formattedAmount}
    </span>
  );
};

// ===== Approval Card Component =====

export const ApprovalCard: React.FC<ApprovalCardProps> = ({
  card,
  onApprove,
  onReject,
  onForward,
  onEmailClick,
  compact = false,
}) => {
  const [loading, setLoading] = useState(false);
  const [comment, setComment] = useState('');
  const [showForward, setShowForward] = useState(false);
  const [forwardTo, setForwardTo] = useState('');
  const [confirmLarge, setConfirmLarge] = useState(false);
  const [expanded, setExpanded] = useState(!compact);

  const handleApprove = useCallback(async () => {
    // Large amount double confirmation
    if (card.is_large_amount && !confirmLarge) {
      setConfirmLarge(true);
      return;
    }

    setLoading(true);
    try {
      await onApprove(card.card_id, comment);
      setConfirmLarge(false);
      setComment('');
    } finally {
      setLoading(false);
    }
  }, [card, comment, confirmLarge, onApprove]);

  const handleReject = useCallback(async () => {
    setLoading(true);
    try {
      await onReject(card.card_id, comment);
      setComment('');
    } finally {
      setLoading(false);
    }
  }, [card, comment, onReject]);

  const handleForward = useCallback(async () => {
    if (!forwardTo.trim()) return;
    setLoading(true);
    try {
      await onForward(card.card_id, forwardTo, comment);
      setShowForward(false);
      setForwardTo('');
      setComment('');
    } finally {
      setLoading(false);
    }
  }, [card, comment, forwardTo, onForward]);

  const isProcessed = card.status !== 'pending';

  return (
    <div className={`approval-card ${isProcessed ? 'processed' : ''} ${card.confidence_level}`}>
      {/* Header */}
      <div className="card-header" onClick={() => onEmailClick?.(card.email_id)}>
        <div className="card-title-row">
          <h3 className="card-subject" title={card.subject}>
            {card.subject}
          </h3>
          <ConfidenceBadge level={card.confidence_level} confidence={card.confidence} />
        </div>
        
        <div className="card-meta">
          {card.requester && (
            <span className="card-requester">来自: {card.requester}</span>
          )}
          {card.deadline && (
            <span className="card-deadline">截止: {card.deadline}</span>
          )}
        </div>
      </div>

      {/* Amount & Status */}
      <div className="card-badges">
        <AmountBadge amount={card.amount} category={card.amount_category} currency={card.currency} />
        {isProcessed && (
          <span className={`status-badge status-${card.status}`}>
            {statusLabel(card.status)}
          </span>
        )}
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="card-details">
          {card.reason && (
            <p className="card-reason">{card.reason}</p>
          )}

          {/* Comment input */}
          {!isProcessed && (
            <div className="card-comment">
              <input
                type="text"
                placeholder="添加备注（可选）"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                className="comment-input"
              />
            </div>
          )}

          {/* Forward input */}
          {showForward && !isProcessed && (
            <div className="card-forward">
              <input
                type="text"
                placeholder="转发给（邮箱地址）"
                value={forwardTo}
                onChange={(e) => setForwardTo(e.target.value)}
                className="forward-input"
              />
            </div>
          )}

          {/* Large amount confirmation */}
          {confirmLarge && (
            <div className="confirm-large">
              <p>⚠️ 大额审批（¥{card.amount?.toLocaleString()}），请确认</p>
              <button className="btn-confirm" onClick={handleApprove} disabled={loading}>
                确认批准
              </button>
              <button className="btn-cancel" onClick={() => setConfirmLarge(false)}>
                取消
              </button>
            </div>
          )}

          {/* Action buttons */}
          {!isProcessed && !confirmLarge && (
            <div className="card-actions">
              {card.is_small_amount ? (
                // Small amount: 3-step simplified flow
                <>
                  <button className="btn-approve" onClick={handleApprove} disabled={loading}>
                    ✓ 批准
                  </button>
                  <button className="btn-reject" onClick={handleReject} disabled={loading}>
                    ✗ 拒绝
                  </button>
                </>
              ) : (
                // Standard/Large flow
                <>
                  <button className="btn-approve" onClick={handleApprove} disabled={loading}>
                    ✓ 批准
                  </button>
                  <button className="btn-reject" onClick={handleReject} disabled={loading}>
                    ✗ 拒绝
                  </button>
                  <button
                    className="btn-forward"
                    onClick={() => setShowForward(!showForward)}
                    disabled={loading}
                  >
                    ↗ {showForward ? '取消转发' : '转发'}
                  </button>
                  {showForward && forwardTo && (
                    <button className="btn-forward-confirm" onClick={handleForward} disabled={loading}>
                      确认转发
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Expand/collapse toggle */}
      <button className="btn-expand" onClick={() => setExpanded(!expanded)}>
        {expanded ? '▲ 收起' : '▼ 展开'}
      </button>
    </div>
  );
};

// ===== Batch Approval Bar =====

export interface BatchApprovalBarProps {
  selectedIds: string[];
  onBatchApprove: (ids: string[], skipLarge: boolean) => Promise<void>;
  onBatchReject: (ids: string[]) => Promise<void>;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  totalPending: number;
}

export const BatchApprovalBar: React.FC<BatchApprovalBarProps> = ({
  selectedIds,
  onBatchApprove,
  onBatchReject,
  onSelectAll,
  onDeselectAll,
  totalPending,
}) => {
  const [loading, setLoading] = useState(false);
  const [skipLarge, setSkipLarge] = useState(true);

  const handleBatchApprove = async () => {
    setLoading(true);
    try {
      await onBatchApprove(selectedIds, skipLarge);
    } finally {
      setLoading(false);
    }
  };

  const handleBatchReject = async () => {
    setLoading(true);
    try {
      await onBatchReject(selectedIds);
    } finally {
      setLoading(false);
    }
  };

  if (selectedIds.length === 0) return null;

  return (
    <div className="batch-approval-bar">
      <span className="batch-count">已选 {selectedIds.length}/{totalPending} 项</span>
      
      <div className="batch-actions">
        <button className="btn-batch-approve" onClick={handleBatchApprove} disabled={loading}>
          ✓ 批量批准{skipLarge ? '（跳过大额）' : ''}
        </button>
        <button className="btn-batch-reject" onClick={handleBatchReject} disabled={loading}>
          ✗ 批量拒绝
        </button>
      </div>

      <div className="batch-options">
        <label className="skip-large-toggle">
          <input
            type="checkbox"
            checked={skipLarge}
            onChange={(e) => setSkipLarge(e.target.checked)}
          />
          跳过大额审批
        </label>
      </div>

      <div className="batch-select">
        <button className="btn-select-all" onClick={onSelectAll}>全选</button>
        <button className="btn-deselect-all" onClick={onDeselectAll}>取消全选</button>
      </div>
    </div>
  );
};

// ===== Approval List Component =====

export interface ApprovalListProps {
  cards: ApprovalCardData[];
  onApprove: (cardId: string, comment?: string) => Promise<void>;
  onReject: (cardId: string, comment?: string) => Promise<void>;
  onForward: (cardId: string, forwardTo: string, comment?: string) => Promise<void>;
  onEmailClick?: (emailId: string) => void;
  onBatchApprove: (ids: string[], skipLarge: boolean) => Promise<void>;
  onBatchReject: (ids: string[]) => Promise<void>;
}

export const ApprovalList: React.FC<ApprovalListProps> = ({
  cards,
  onApprove,
  onReject,
  onForward,
  onEmailClick,
  onBatchApprove,
  onBatchReject,
}) => {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filterConfidence, setFilterConfidence] = useState<ConfidenceLevel | 'all'>('all');

  const toggleSelect = (cardId: string) => {
    const next = new Set(selectedIds);
    if (next.has(cardId)) {
      next.delete(cardId);
    } else {
      next.add(cardId);
    }
    setSelectedIds(next);
  };

  const selectAll = () => {
    const allIds = filteredCards.map((c) => c.card_id);
    setSelectedIds(new Set(allIds));
  };

  const deselectAll = () => setSelectedIds(new Set());

  const filteredCards = filterConfidence === 'all'
    ? cards
    : cards.filter((c) => c.confidence_level === filterConfidence);

  const pendingCards = cards.filter((c) => c.status === 'pending');

  return (
    <div className="approval-list">
      {/* Filter bar */}
      <div className="approval-filter-bar">
        <span className="filter-label">筛选：</span>
        {(['all', 'high', 'medium', 'low'] as const).map((level) => (
          <button
            key={level}
            className={`filter-btn ${filterConfidence === level ? 'active' : ''}`}
            onClick={() => setFilterConfidence(level)}
          >
            {level === 'all' ? '全部' : level === 'high' ? '🟢 高' : level === 'medium' ? '🟡 中' : '🔴 低'}
          </button>
        ))}
        <span className="pending-count">{pendingCards.length} 项待审批</span>
      </div>

      {/* Batch approval bar */}
      <BatchApprovalBar
        selectedIds={Array.from(selectedIds)}
        onBatchApprove={onBatchApprove}
        onBatchReject={onBatchReject}
        onSelectAll={selectAll}
        onDeselectAll={deselectAll}
        totalPending={pendingCards.length}
      />

      {/* Card list */}
      <div className="approval-cards">
        {filteredCards.map((card) => (
          <div key={card.card_id} className="approval-card-wrapper">
            {card.status === 'pending' && (
              <input
                type="checkbox"
                className="card-checkbox"
                checked={selectedIds.has(card.card_id)}
                onChange={() => toggleSelect(card.card_id)}
              />
            )}
            <ApprovalCard
              card={card}
              onApprove={onApprove}
              onReject={onReject}
              onForward={onForward}
              onEmailClick={onEmailClick}
              compact
            />
          </div>
        ))}

        {filteredCards.length === 0 && (
          <div className="empty-state">
            <p>暂无审批邮件</p>
          </div>
        )}
      </div>
    </div>
  );
};

// ===== Helper =====

function statusLabel(status: ApprovalStatus): string {
  const labels: Record<ApprovalStatus, string> = {
    pending: '待审批',
    approved: '已批准',
    rejected: '已拒绝',
    forwarded: '已转发',
    delegated: '已委托',
    deferred: '已延期',
    expired: '已过期',
  };
  return labels[status] || status;
}

export default ApprovalCard;

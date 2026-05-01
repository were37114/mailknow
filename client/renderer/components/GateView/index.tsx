/**
 * GateView - Gate 4档视图组件
 * 
 * 将内部5级Gate分类映射为用户友好的4档视图：
 * - ⭐ 重要：G2重要 + G4审批
 * - 📬 一般：G3一般
 * - 🔔 通知：G1通知
 * - 🗑️ 垃圾：G0垃圾
 */

import React, { useState, useMemo, useCallback } from 'react';

// ===== Types =====

export type GateTier = 'important' | 'routine' | 'notification' | 'spam';

export interface GateEmailData {
  email_id: string;
  subject: string;
  sender: string;
  sender_name?: string;
  preview: string;
  date: string;
  gate_class: 'G0' | 'G1' | 'G2' | 'G3' | 'G4';
  has_attachment: boolean;
  is_unread: boolean;
  amount?: number;
  confidence?: number;
}

export interface GateViewProps {
  emails: GateEmailData[];
  onEmailClick: (emailId: string) => void;
  onRefresh?: () => Promise<void>;
  loading?: boolean;
}

// ===== Gate Tier Mapping =====

const GATE_CLASS_TO_TIER: Record<string, GateTier> = {
  'G0': 'spam',
  'G1': 'notification',
  'G2': 'important',
  'G3': 'routine',
  'G4': 'important',  // 审批邮件归入重要
};

const TIER_CONFIG: Record<GateTier, { label: string; icon: string; className: string }> = {
  important: { label: '重要', icon: '⭐', className: 'tier-important' },
  routine: { label: '一般', icon: '📬', className: 'tier-routine' },
  notification: { label: '通知', icon: '🔔', className: 'tier-notification' },
  spam: { label: '垃圾', icon: '🗑️', className: 'tier-spam' },
};

// ===== Gate Tier Tab Component =====

interface GateTierTabProps {
  tier: GateTier;
  count: number;
  active: boolean;
  onClick: () => void;
}

const GateTierTab: React.FC<GateTierTabProps> = ({ tier, count, active, onClick }) => {
  const config = TIER_CONFIG[tier];
  
  return (
    <button
      className={`gate-tab ${config.className} ${active ? 'active' : ''}`}
      onClick={onClick}
    >
      <span className="tab-icon">{config.icon}</span>
      <span className="tab-label">{config.label}</span>
      <span className="tab-count">{count}</span>
    </button>
  );
};

// ===== Email Item Component =====

interface EmailItemProps {
  email: GateEmailData;
  onClick: () => void;
}

const EmailItem: React.FC<EmailItemProps> = ({ email, onClick }) => {
  const formattedDate = useMemo(() => {
    const d = new Date(email.date);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) {
      return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    } else if (diffDays < 7) {
      return `${diffDays}天前`;
    } else {
      return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    }
  }, [email.date]);

  return (
    <div 
      className={`email-item ${email.is_unread ? 'unread' : ''}`}
      onClick={onClick}
    >
      {/* Avatar */}
      <div className="email-avatar">
        {email.sender_name?.charAt(0) || email.sender.charAt(0).toUpperCase()}
      </div>

      {/* Content */}
      <div className="email-content">
        <div className="email-header">
          <span className="email-sender">
            {email.sender_name || email.sender.split('@')[0]}
          </span>
          <span className="email-date">{formattedDate}</span>
        </div>
        
        <div className="email-subject" title={email.subject}>
          {email.subject}
        </div>
        
        <div className="email-preview" title={email.preview}>
          {email.preview}
        </div>
      </div>

      {/* Meta */}
      <div className="email-meta">
        {email.has_attachment && (
          <span className="meta-icon" title="有附件">📎</span>
        )}
        {email.gate_class === 'G4' && (
          <span className="meta-badge approval" title="审批邮件">审批</span>
        )}
        {email.amount && (
          <span className="meta-badge amount">
            ¥{email.amount >= 10000 ? `${(email.amount / 10000).toFixed(1)}万` : email.amount}
          </span>
        )}
      </div>
    </div>
  );
};

// ===== Gate View Component =====

export const GateView: React.FC<GateViewProps> = ({
  emails,
  onEmailClick,
  onRefresh,
  loading = false,
}) => {
  const [activeTier, setActiveTier] = useState<GateTier>('important');

  // 分组统计
  const tierCounts = useMemo(() => {
    const counts: Record<GateTier, number> = {
      important: 0,
      routine: 0,
      notification: 0,
      spam: 0,
    };
    
    emails.forEach((email) => {
      const tier = GATE_CLASS_TO_TIER[email.gate_class] || 'routine';
      counts[tier]++;
    });
    
    return counts;
  }, [emails]);

  // 过滤当前tier的邮件
  const filteredEmails = useMemo(() => {
    return emails.filter((email) => {
      const tier = GATE_CLASS_TO_TIER[email.gate_class] || 'routine';
      return tier === activeTier;
    });
  }, [emails, activeTier]);

  // 未读数
  const unreadCounts = useMemo(() => {
    const counts: Record<GateTier, number> = {
      important: 0,
      routine: 0,
      notification: 0,
      spam: 0,
    };
    
    emails.forEach((email) => {
      if (email.is_unread) {
        const tier = GATE_CLASS_TO_TIER[email.gate_class] || 'routine';
        counts[tier]++;
      }
    });
    
    return counts;
  }, [emails]);

  return (
    <div className="gate-view">
      {/* Header */}
      <div className="gate-header">
        <h2 className="gate-title">邮件分流</h2>
        {onRefresh && (
          <button 
            className="btn-refresh" 
            onClick={onRefresh}
            disabled={loading}
          >
            {loading ? '刷新中...' : '🔄 刷新'}
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="gate-tabs">
        {(['important', 'routine', 'notification', 'spam'] as GateTier[]).map((tier) => (
          <GateTierTab
            key={tier}
            tier={tier}
            count={tierCounts[tier]}
            active={activeTier === tier}
            onClick={() => setActiveTier(tier)}
          />
        ))}
      </div>

      {/* Email List */}
      <div className="gate-email-list">
        {loading && (
          <div className="loading-state">
            <p>加载中...</p>
          </div>
        )}

        {!loading && filteredEmails.length === 0 && (
          <div className="empty-state">
            <p>{TIER_CONFIG[activeTier].icon} 暂无{TIER_CONFIG[activeTier].label}邮件</p>
          </div>
        )}

        {!loading && filteredEmails.length > 0 && (
          <div className="email-list">
            {filteredEmails.map((email) => (
              <EmailItem
                key={email.email_id}
                email={email}
                onClick={() => onEmailClick(email.email_id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Stats Footer */}
      <div className="gate-footer">
        <span className="footer-stat">
          共 {emails.length} 封邮件
        </span>
        <span className="footer-stat">
          未读 {Object.values(unreadCounts).reduce((a, b) => a + b, 0)} 封
        </span>
      </div>
    </div>
  );
};

export default GateView;

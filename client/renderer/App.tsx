import React, { useState, useEffect, useCallback, useRef } from 'react';

// ===== Type Definitions =====

interface EmailAddress {
  name: string;
  address: string;
}

interface EmailItem {
  id: string;
  subject: string;
  from: EmailAddress;
  to: EmailAddress[];
  date: string;
  gateClass: string;
  gateScore: number;
  isRead: boolean;
  hasAttachments: boolean;
  preview: string;
}

interface EmailListResponse {
  emails: EmailItem[];
  total: number;
  page: number;
  pageSize: number;
}

interface GateStats {
  important: number;   // urgent + important
  routine: number;     // routine + notification
  spam: number;        // spam
  total: number;
}

interface SearchResponse {
  results: EmailItem[];
  total: number;
  query: string;
}

// Extend window type for our API
declare global {
  interface Window {
    mailknowAPI: {
      listEmails: (args?: { folder?: string; page?: number; pageSize?: number; gateClass?: string }) => Promise<EmailListResponse>;
      getEmail: (emailId: string) => Promise<any>;
      classifyEmail: (emailId: string) => Promise<any>;
      listAccounts: () => Promise<any>;
      addAccount: (account: any) => Promise<any>;
      removeAccount: (accountId: string) => Promise<any>;
      startSync: (accountId: string) => Promise<any>;
      getSyncStatus: () => Promise<any>;
      search: (args: { query: string; page?: number; pageSize?: number }) => Promise<SearchResponse>;
      getGateStats: () => Promise<GateStats>;
      getTokenUsage: () => Promise<TokenUsageData>;
      setTokenBudget: (config: any) => Promise<any>;
      onSyncProgress: (callback: (progress: any) => void) => void;
      onNewEmail: (callback: (email: any) => void) => void;
      // Auto Update APIs
      checkForUpdate: () => Promise<{ available: boolean; version?: string; error?: string }>;
      downloadUpdate: () => Promise<{ success: boolean; error?: string }>;
      installUpdate: () => void;
      getAppVersion: () => Promise<{ version: string; name: string; platform: string; arch: string }>;
      onUpdateChecking: (callback: () => void) => void;
      onUpdateAvailable: (callback: (info: any) => void) => void;
      onUpdateNotAvailable: (callback: (info: any) => void) => void;
      onUpdateProgress: (callback: (progress: { percent: number; transferred: number; total: number }) => void) => void;
      onUpdateDownloaded: (callback: (info: any) => void) => void;
      onUpdateError: (callback: (error: any) => void) => void;
      removeAllListeners: (channel: string) => void;
    };
  }
}

// Token usage data
interface TokenUsageData {
  dailyTokens: number;
  dailyCost: number;
  dailyLimit: number;
  monthlyTokens: number;
  monthlyCost: number;
  monthlyLimit: number;
  degradation: string;
  byTask: Record<string, number>;
}

// ===== Gate 4-Tier Display Config (V5.2 spec) =====
// G0 urgent + G1 important → ⭐ 重要
// G2 routine + G3 notification → 📬 一般
// G4 spam → 🗑️ 垃圾

type GateTier = 'important' | 'routine' | 'spam';

const GATE_TIER_MAP: Record<string, GateTier> = {
  urgent: 'important',
  important: 'important',
  routine: 'routine',
  notification: 'routine',
  spam: 'spam',
};

const TIER_CONFIG: Record<GateTier, { label: string; icon: string; color: string; bgColor: string; borderColor: string }> = {
  important: { label: '重要', icon: '⭐', color: '#dc2626', bgColor: '#fef2f2', borderColor: '#ef4444' },
  routine: { label: '一般', icon: '📬', color: '#6b7280', bgColor: '#f9fafb', borderColor: '#d1d5db' },
  spam: { label: '垃圾', icon: '🗑️', color: '#9ca3af', bgColor: '#f3f4f6', borderColor: '#9ca3af' },
};

// Sub-classes within each tier (shown as subtle badges)
const GATE_SUBCLASS: Record<string, string> = {
  urgent: '紧急',
  important: '重要',
  routine: '常规',
  notification: '通知',
  spam: '垃圾',
};

// ===== Utility Functions =====

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return '刚刚';
  if (diffMins < 60) return `${diffMins}分钟前`;
  if (diffHours < 24) return `${diffHours}小时前`;
  if (diffDays < 7) return `${diffDays}天前`;
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

function formatSender(from: EmailAddress): string {
  return from.name || from.address.split('@')[0];
}

// ===== Components =====

const Sidebar: React.FC<{
  selectedTier: GateTier | null;
  onSelectTier: (tier: GateTier | null) => void;
  gateStats: GateStats;
  isSearching: boolean;
}> = ({ selectedTier, onSelectTier, gateStats, isSearching }) => {
  return (
    <div style={{
      width: '200px',
      background: '#16213e',
      color: '#e2e8f0',
      display: 'flex',
      flexDirection: 'column',
      borderRight: '1px solid #1a1a3e',
      userSelect: 'none',
    }}>
      {/* Logo */}
      <div style={{
        padding: '16px 20px',
        fontSize: '20px',
        fontWeight: 700,
        borderBottom: '1px solid rgba(255,255,255,0.1)',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
      }}>
        📧 MailKnow
      </div>

      {/* Gate 4-tier filters */}
      <div style={{ padding: '12px 0' }}>
        <SidebarItem
          icon="📥"
          label="全部邮件"
          count={gateStats.total}
          active={selectedTier === null && !isSearching}
          onClick={() => onSelectTier(null)}
        />
        
        {(Object.entries(TIER_CONFIG) as [GateTier, typeof TIER_CONFIG[GateTier]][]).map(([key, config]) => (
          <SidebarItem
            key={key}
            icon={config.icon}
            label={config.label}
            count={gateStats[key] || 0}
            active={selectedTier === key && !isSearching}
            onClick={() => onSelectTier(key)}
          />
        ))}
      </div>

      {/* Search indicator */}
      {isSearching && (
        <div style={{
          padding: '8px 20px',
          fontSize: '13px',
          color: '#667eea',
          background: 'rgba(102, 126, 234, 0.1)',
          borderLeft: '3px solid #667eea',
          marginTop: '4px',
        }}>
          🔍 搜索结果
        </div>
      )}

      {/* Token Budget Panel - needs tokenUsage from parent */}
      {/* Rendered in App layer instead */}

      {/* Settings */}
      <div style={{
        padding: '12px 20px',
        borderTop: '1px solid rgba(255,255,255,0.1)',
        fontSize: '13px',
        opacity: 0.6,
      }}>
        ⚙️ 设置
      </div>
    </div>
  );
};

const SidebarItem: React.FC<{
  icon: string;
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}> = ({ icon, label, count, active, onClick }) => (
  <div
    onClick={onClick}
    style={{
      padding: '8px 20px',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: '10px',
      background: active ? 'rgba(102, 126, 234, 0.2)' : 'transparent',
      borderLeft: active ? '3px solid #667eea' : '3px solid transparent',
      transition: 'all 0.15s ease',
    }}
  >
    <span>{icon}</span>
    <span style={{ flex: 1, fontSize: '14px' }}>{label}</span>
    {count > 0 && (
      <span style={{
        background: active ? '#667eea' : 'rgba(255,255,255,0.15)',
        borderRadius: '10px',
        padding: '1px 8px',
        fontSize: '12px',
      }}>
        {count}
      </span>
    )}
  </div>
);

const SearchBox: React.FC<{
  value: string;
  onChange: (value: string) => void;
  onSearch: (query: string) => void;
  onClear: () => void;
  placeholder?: string;
}> = ({ value, onChange, onSearch, onClear, placeholder = '搜索邮件、联系人、项目...' }) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isFocused, setIsFocused] = useState(false);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && value.trim()) {
      onSearch(value.trim());
    }
    if (e.key === 'Escape') {
      onClear();
      inputRef.current?.blur();
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      flex: 1,
      position: 'relative',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        flex: 1,
        background: isFocused ? '#ffffff' : '#f9fafb',
        border: `1px solid ${isFocused ? '#667eea' : '#e5e7eb'}`,
        borderRadius: '8px',
        padding: '0 12px',
        transition: 'all 0.15s ease',
        boxShadow: isFocused ? '0 0 0 3px rgba(102,126,234,0.1)' : 'none',
      }}>
        <span style={{ fontSize: '14px', color: '#9ca3af' }}>🔍</span>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={placeholder}
          style={{
            flex: 1,
            padding: '8px 10px',
            border: 'none',
            background: 'transparent',
            fontSize: '14px',
            outline: 'none',
            color: '#1f2937',
          }}
        />
        {value && (
          <button
            onClick={onClear}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: '14px',
              color: '#9ca3af',
              padding: '2px',
            }}
          >
            ✕
          </button>
        )}
      </div>
      {value.trim() && (
        <button
          onClick={() => onSearch(value.trim())}
          style={{
            padding: '8px 16px',
            background: '#667eea',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            fontSize: '14px',
            cursor: 'pointer',
            fontWeight: 500,
          }}
        >
          搜索
        </button>
      )}
    </div>
  );
};

const GateBadge: React.FC<{
  gateClass: string;
  compact?: boolean;
}> = ({ gateClass, compact = false }) => {
  const tier = GATE_TIER_MAP[gateClass] || 'routine';
  const config = TIER_CONFIG[tier];
  const subLabel = GATE_SUBCLASS[gateClass] || gateClass;

  if (compact) {
    return (
      <span style={{
        fontSize: '11px',
        padding: '1px 6px',
        borderRadius: '4px',
        background: config.bgColor,
        color: config.color,
        whiteSpace: 'nowrap',
      }}>
        {config.icon} {subLabel}
      </span>
    );
  }

  return (
    <span style={{
      fontSize: '12px',
      padding: '2px 8px',
      borderRadius: '12px',
      background: config.bgColor,
      color: config.color,
      whiteSpace: 'nowrap',
    }}>
      {config.icon} {subLabel}
    </span>
  );
};

const EmailRow: React.FC<{
  email: EmailItem;
  isSelected: boolean;
  onSelect: () => void;
}> = ({ email, isSelected, onSelect }) => {
  const tier = GATE_TIER_MAP[email.gateClass] || 'routine';
  const tierConfig = TIER_CONFIG[tier];

  return (
    <div
      onClick={onSelect}
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '12px 20px',
        borderBottom: '1px solid #f0f0f5',
        background: isSelected ? '#eef2ff' : (email.isRead ? '#ffffff' : '#fafbff'),
        cursor: 'pointer',
        transition: 'background 0.15s ease',
        borderLeft: `3px solid ${tierConfig.borderColor}`,
      }}
    >
      {/* Unread indicator */}
      <div style={{
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: email.isRead ? 'transparent' : '#667eea',
        marginRight: '12px',
        flexShrink: 0,
      }} />

      {/* Sender */}
      <div style={{
        width: '90px',
        fontWeight: email.isRead ? 400 : 600,
        fontSize: '14px',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}>
        {formatSender(email.from)}
      </div>

      {/* Subject + Preview */}
      <div style={{ flex: 1, overflow: 'hidden', marginLeft: '12px' }}>
        <div style={{
          fontWeight: email.isRead ? 400 : 600,
          fontSize: '14px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {email.subject}
          </span>
          {email.hasAttachments && <span>📎</span>}
        </div>
        <div style={{
          fontSize: '12px',
          color: '#9ca3af',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          marginTop: '2px',
        }}>
          {email.preview}
        </div>
      </div>

      {/* Gate badge */}
      <div style={{ marginLeft: '10px', flexShrink: 0 }}>
        <GateBadge gateClass={email.gateClass} compact />
      </div>

      {/* Date */}
      <div style={{
        fontSize: '12px',
        color: '#9ca3af',
        marginLeft: '10px',
        flexShrink: 0,
        minWidth: '60px',
        textAlign: 'right',
      }}>
        {formatDate(email.date)}
      </div>
    </div>
  );
};

const EmailDetail: React.FC<{
  email: EmailItem | null;
  onClose: () => void;
}> = ({ email, onClose }) => {
  if (!email) return null;

  const tier = GATE_TIER_MAP[email.gateClass] || 'routine';
  const tierConfig = TIER_CONFIG[tier];

  return (
    <div style={{
      width: '400px',
      borderLeft: '1px solid #e5e7eb',
      background: '#ffffff',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'auto',
    }}>
      {/* Header */}
      <div style={{
        padding: '16px 20px',
        borderBottom: '1px solid #e5e7eb',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
      }}>
        <button onClick={onClose} style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: '18px',
          padding: '4px',
        }}>←</button>
        <span style={{ flex: 1, fontWeight: 600, fontSize: '14px' }}>邮件详情</span>
        <GateBadge gateClass={email.gateClass} />
      </div>

      {/* Content */}
      <div style={{ padding: '20px', flex: 1 }}>
        <h2 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px' }}>
          {email.subject}
        </h2>

        <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '8px' }}>
          <strong>发件人：</strong>{email.from.name} &lt;{email.from.address}&gt;
        </div>
        <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '8px' }}>
          <strong>收件人：</strong>{email.to.map(t => t.address).join(', ')}
        </div>
        <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '16px' }}>
          <strong>时间：</strong>{new Date(email.date).toLocaleString('zh-CN')}
        </div>

        {/* Gate info */}
        <div style={{
          padding: '10px 14px',
          background: tierConfig.bgColor,
          borderRadius: '8px',
          borderLeft: `3px solid ${tierConfig.color}`,
          marginBottom: '16px',
          fontSize: '13px',
          color: tierConfig.color,
        }}>
          {tierConfig.icon} Gate分流：<strong>{GATE_SUBCLASS[email.gateClass]}</strong>
          {email.gateScore > 0 && (
            <span style={{ marginLeft: '8px', opacity: 0.7 }}>
              置信度 {(email.gateScore * 100).toFixed(0)}%
            </span>
          )}
        </div>

        <div style={{
          borderTop: '1px solid #e5e7eb',
          paddingTop: '16px',
          fontSize: '14px',
          lineHeight: 1.8,
          color: '#374151',
        }}>
          {email.preview}
        </div>
      </div>
    </div>
  );
};

const LoadingSpinner: React.FC = () => (
  <div style={{
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    padding: '40px',
    color: '#9ca3af',
  }}>
    <div style={{
      width: '24px',
      height: '24px',
      border: '3px solid #e5e7eb',
      borderTopColor: '#667eea',
      borderRadius: '50%',
      animation: 'spin 0.8s linear infinite',
    }} />
    <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    <span style={{ marginLeft: '12px' }}>加载中...</span>
  </div>
);

const EmptyState: React.FC<{
  isSearch: boolean;
  query?: string;
}> = ({ isSearch, query }) => (
  <div style={{
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '60px 20px',
    color: '#9ca3af',
  }}>
    <span style={{ fontSize: '48px', marginBottom: '16px' }}>
      {isSearch ? '🔍' : '📭'}
    </span>
    <div style={{ fontSize: '16px', fontWeight: 500, marginBottom: '8px' }}>
      {isSearch ? `未找到"${query}"相关邮件` : '暂无邮件'}
    </div>
    <div style={{ fontSize: '13px' }}>
      {isSearch ? '试试其他关键词' : '新邮件同步后将显示在这里'}
    </div>
  </div>
);

const TokenPanel: React.FC<{
  usage: TokenUsageData | null;
}> = ({ usage }) => {
  if (!usage) return null;

  const dailyRatio = usage.dailyTokens / usage.dailyLimit;
  const monthlyRatio = usage.monthlyTokens / usage.monthlyLimit;
  
  const degradationColors: Record<string, string> = {
    normal: '#22c55e',
    warning: '#f59e0b',
    degraded: '#ef4444',
    pure_gbrain: '#9ca3af',
  };
  const degradationLabels: Record<string, string> = {
    normal: '正常',
    warning: '接近上限',
    degraded: '已降级',
    pure_gbrain: '纯本地',
  };

  const barColor = degradationColors[usage.degradation] || '#667eea';

  return (
    <div style={{
      marginTop: 'auto',
      padding: '12px 16px',
      borderTop: '1px solid rgba(255,255,255,0.1)',
      fontSize: '12px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
        <span>🪙</span>
        <span style={{ fontWeight: 500, color: '#e2e8f0' }}>Token 用量</span>
        <span style={{
          marginLeft: 'auto',
          fontSize: '10px',
          padding: '1px 5px',
          borderRadius: '4px',
          background: `${barColor}22`,
          color: barColor,
        }}>
          {degradationLabels[usage.degradation]}
        </span>
      </div>
      
      {/* Daily bar */}
      <div style={{ marginBottom: '6px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px', color: '#94a3b8' }}>
          <span>今日</span>
          <span>{(usage.dailyTokens / 1000).toFixed(0)}K / {(usage.dailyLimit / 1000).toFixed(0)}K</span>
        </div>
        <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px' }}>
          <div style={{
            height: '100%',
            width: `${Math.min(dailyRatio * 100, 100)}%`,
            background: barColor,
            borderRadius: '2px',
            transition: 'width 0.3s ease',
          }} />
        </div>
      </div>
      
      {/* Monthly bar */}
      <div style={{ marginBottom: '6px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px', color: '#94a3b8' }}>
          <span>本月</span>
          <span>{(usage.monthlyTokens / 1000000).toFixed(1)}M / {(usage.monthlyLimit / 1000000).toFixed(0)}M</span>
        </div>
        <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px' }}>
          <div style={{
            height: '100%',
            width: `${Math.min(monthlyRatio * 100, 100)}%`,
            background: monthlyRatio > 0.9 ? '#ef4444' : '#667eea',
            borderRadius: '2px',
            transition: 'width 0.3s ease',
          }} />
        </div>
      </div>
      
      {/* Cost */}
      <div style={{ color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
        <span>费用</span>
        <span>今日 ${usage.dailyCost.toFixed(2)} / 本月 ${usage.monthlyCost.toFixed(2)}</span>
      </div>
    </div>
  );
};

// ===== Main App =====

const App: React.FC = () => {
  const [emails, setEmails] = useState<EmailItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTier, setSelectedTier] = useState<GateTier | null>(null);
  const [selectedEmail, setSelectedEmail] = useState<EmailItem | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [gateStats, setGateStats] = useState<GateStats>({ important: 0, routine: 0, spam: 0, total: 0 });
  const [tokenUsage, setTokenUsage] = useState<TokenUsageData | null>(null);
  
  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<EmailItem[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);

  // Display emails (normal or search results)
  const displayEmails = isSearching ? searchResults : emails;
  const displayTotal = isSearching ? searchTotal : total;

  const loadEmails = useCallback(async (tier: GateTier | null, pageNum: number = 1) => {
    setLoading(true);
    try {
      const api = window.mailknowAPI;
      if (api) {
        // Map tier to gate classes for API query
        const gateClasses = tier ? getGateClassesForTier(tier) : undefined;
        
        // Query each gate class and merge
        let allEmails: EmailItem[] = [];
        let totalCount = 0;

        if (gateClasses && gateClasses.length > 0) {
          for (const gc of gateClasses) {
            const response = await api.listEmails({
              gateClass: gc,
              page: pageNum,
              pageSize: 50,
            });
            allEmails = allEmails.concat(response.emails);
            totalCount += response.total;
          }
          // Sort by date
          allEmails.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
        } else {
          const response = await api.listEmails({
            page: pageNum,
            pageSize: 50,
          });
          allEmails = response.emails;
          totalCount = response.total;
        }

        setEmails(allEmails);
        setTotal(totalCount);
        setPage(pageNum);
      }
    } catch (err) {
      console.error('Failed to load emails:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadGateStats = useCallback(async () => {
    try {
      const api = window.mailknowAPI;
      if (api?.getGateStats) {
        const stats = await api.getGateStats();
        setGateStats(stats);
      }
    } catch (err) {
      console.error('Failed to load gate stats:', err);
    }
  }, []);

  const loadTokenUsage = useCallback(async () => {
    try {
      const api = window.mailknowAPI;
      if (api?.getTokenUsage) {
        const usage = await api.getTokenUsage();
        setTokenUsage(usage);
      }
    } catch (err) {
      console.error('Failed to load token usage:', err);
    }
  }, []);

  useEffect(() => {
    loadEmails(selectedTier);
    loadGateStats();
    loadTokenUsage();
  }, [selectedTier, loadEmails, loadGateStats, loadTokenUsage]);

  const handleSelectTier = (tier: GateTier | null) => {
    setSelectedTier(tier);
    setSelectedEmail(null);
    setIsSearching(false);
    setSearchQuery('');
  };

  const handleSearch = useCallback(async (query: string) => {
    if (!query.trim()) return;
    
    setLoading(true);
    setIsSearching(true);
    try {
      const api = window.mailknowAPI;
      if (api) {
        const response = await api.search({ query: query.trim(), pageSize: 50 });
        setSearchResults(response.results || []);
        setSearchTotal(response.total || 0);
      }
    } catch (err) {
      console.error('Search failed:', err);
      setSearchResults([]);
      setSearchTotal(0);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleClearSearch = useCallback(() => {
    setSearchQuery('');
    setIsSearching(false);
    setSearchResults([]);
    setSearchTotal(0);
  }, []);

  // Keyboard shortcut: Cmd/Ctrl+K to focus search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        (document.querySelector('input[type="text"]') as HTMLInputElement)?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      background: '#f8fafc',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      {/* Sidebar */}
      <Sidebar
        selectedTier={selectedTier}
        onSelectTier={handleSelectTier}
        gateStats={gateStats}
        isSearching={isSearching}
      />
      
      {/* Token usage panel (below sidebar) */}
      <TokenPanel usage={tokenUsage} />

      {/* Email List */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
      }}>
        {/* Toolbar */}
        <div style={{
          padding: '12px 20px',
          borderBottom: '1px solid #e5e7eb',
          background: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
        }}>
          <SearchBox
            value={searchQuery}
            onChange={setSearchQuery}
            onSearch={handleSearch}
            onClear={handleClearSearch}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '11px', color: '#d1d5db', padding: '2px 6px', background: '#f3f4f6', borderRadius: '4px' }}>
              ⌘K
            </span>
            <span style={{ fontSize: '13px', color: '#9ca3af' }}>
              {isSearching ? `${displayTotal} 条结果` : `共 ${displayTotal} 封`}
            </span>
          </div>
        </div>

        {/* Gate tier header (when filtered) */}
        {selectedTier && !isSearching && (
          <div style={{
            padding: '8px 20px',
            background: TIER_CONFIG[selectedTier].bgColor,
            borderBottom: `1px solid ${TIER_CONFIG[selectedTier].borderColor}`,
            fontSize: '13px',
            color: TIER_CONFIG[selectedTier].color,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}>
            {TIER_CONFIG[selectedTier].icon} {TIER_CONFIG[selectedTier].label}邮件
            <span style={{ opacity: 0.6, fontSize: '12px' }}>
              {selectedTier === 'important' ? '(紧急 + 重要)' : 
               selectedTier === 'routine' ? '(常规 + 通知)' : ''}
            </span>
          </div>
        )}

        {/* Email list */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading ? (
            <LoadingSpinner />
          ) : displayEmails.length === 0 ? (
            <EmptyState isSearch={isSearching} query={searchQuery} />
          ) : (
            displayEmails.map((email) => (
              <EmailRow
                key={email.id}
                email={email}
                isSelected={selectedEmail?.id === email.id}
                onSelect={() => setSelectedEmail(email)}
              />
            ))
          )}
        </div>

        {/* Pagination */}
        {displayTotal > 50 && !isSearching && (
          <div style={{
            padding: '8px 20px',
            borderTop: '1px solid #e5e7eb',
            display: 'flex',
            justifyContent: 'center',
            gap: '8px',
            fontSize: '13px',
          }}>
            <button
              disabled={page <= 1}
              onClick={() => loadEmails(selectedTier, page - 1)}
              style={{
                padding: '4px 12px',
                border: '1px solid #e5e7eb',
                borderRadius: '4px',
                background: page <= 1 ? '#f3f4f6' : '#fff',
                cursor: page <= 1 ? 'not-allowed' : 'pointer',
              }}
            >
              上一页
            </button>
            <span style={{ lineHeight: '28px' }}>
              第 {page} 页
            </span>
            <button
              onClick={() => loadEmails(selectedTier, page + 1)}
              style={{
                padding: '4px 12px',
                border: '1px solid #e5e7eb',
                borderRadius: '4px',
                background: '#fff',
                cursor: 'pointer',
              }}
            >
              下一页
            </button>
          </div>
        )}
      </div>

      {/* Email Detail */}
      {selectedEmail && (
        <EmailDetail
          email={selectedEmail}
          onClose={() => setSelectedEmail(null)}
        />
      )}
    </div>
  );
};

// ===== Helpers =====

function getGateClassesForTier(tier: GateTier): string[] {
  switch (tier) {
    case 'important': return ['urgent', 'important'];
    case 'routine': return ['routine', 'notification'];
    case 'spam': return ['spam'];
    default: return [];
  }
}

export default App;

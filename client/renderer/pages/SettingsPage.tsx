import React, { useState, useEffect } from 'react';
import './SettingsPage.css';

// ===== Types =====

export interface SettingsData {
  // LLM Settings
  llm_provider: 'openai' | 'anthropic' | 'local' | '';
  api_key: string;
  api_base: string;
  model: string;
  
  // Token Budget
  daily_token_limit: number;
  monthly_token_limit: number;
  monthly_cost_limit: number;
  
  // Gate Settings
  custom_rules_enabled: boolean;
  gate_rules_path: string;
  
  // Scene Settings
  max_daily_cards: number;
  silent_hours_start: number;
  silent_hours_end: number;
  
  // Sync Settings
  sync_interval_minutes: number;
  max_accounts: number;
  
  // Advanced
  debug_mode: boolean;
  data_path: string;
  ipc_socket_path: string;
}

const DEFAULT_SETTINGS: SettingsData = {
  llm_provider: '',
  api_key: '',
  api_base: '',
  model: 'gpt-4o-mini',
  daily_token_limit: 50000,
  monthly_token_limit: 1000000,
  monthly_cost_limit: 10,
  custom_rules_enabled: false,
  gate_rules_path: '',
  max_daily_cards: 5,
  silent_hours_start: 22,
  silent_hours_end: 8,
  sync_interval_minutes: 5,
  max_accounts: 3,
  debug_mode: false,
  data_path: '',
  ipc_socket_path: '',
};

// ===== Settings Page =====

export const SettingsPage: React.FC<{
  settings: SettingsData;
  onSave: (settings: SettingsData) => Promise<void>;
  onReset: () => Promise<void>;
}> = ({ settings: initialSettings, onSave, onReset }) => {
  const [settings, setSettings] = useState<SettingsData>({
    ...DEFAULT_SETTINGS,
    ...initialSettings,
  });
  const [activeTab, setActiveTab] = useState<'llm' | 'budget' | 'gate' | 'scene' | 'sync' | 'advanced'>('llm');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (confirm('确定要重置所有设置吗？')) {
      await onReset();
      setSettings(DEFAULT_SETTINGS);
    }
  };

  const updateSetting = <K extends keyof SettingsData>(key: K, value: SettingsData[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const tabs = [
    { key: 'llm', label: '🤖 LLM配置' },
    { key: 'budget', label: '💰 Token预算' },
    { key: 'gate', label: '🚪 Gate规则' },
    { key: 'scene', label: '📱 场景推荐' },
    { key: 'sync', label: '🔄 邮件同步' },
    { key: 'advanced', label: '⚙️ 高级' },
  ] as const;

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2>设置</h2>
        <div className="settings-actions">
          <button className="btn-save" onClick={handleSave} disabled={saving}>
            {saving ? '保存中...' : saved ? '✓ 已保存' : '保存设置'}
          </button>
          <button className="btn-reset" onClick={handleReset}>重置</button>
        </div>
      </div>

      <div className="settings-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`tab-btn ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="settings-content">
        {activeTab === 'llm' && (
          <div className="settings-section">
            <h3>LLM API 配置（BYOK）</h3>
            <div className="form-group">
              <label>LLM 提供商</label>
              <select value={settings.llm_provider} onChange={(e) => updateSetting('llm_provider', e.target.value as any)}>
                <option value="">未配置</option>
                <option value="openai">OpenAI (GPT-4o-mini)</option>
                <option value="anthropic">Anthropic (Claude Haiku)</option>
                <option value="local">本地模型</option>
              </select>
            </div>
            <div className="form-group">
              <label>API Key</label>
              <div className="api-key-input">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  value={settings.api_key}
                  onChange={(e) => updateSetting('api_key', e.target.value)}
                  placeholder="sk-..."
                />
                <button className="btn-toggle-visibility" onClick={() => setShowApiKey(!showApiKey)}>
                  {showApiKey ? '🙈' : '👁️'}
                </button>
              </div>
            </div>
            <div className="form-group">
              <label>API Base URL（可选）</label>
              <input
                type="text"
                value={settings.api_base}
                onChange={(e) => updateSetting('api_base', e.target.value)}
                placeholder="https://api.openai.com/v1"
              />
            </div>
            <div className="form-group">
              <label>模型</label>
              <input
                type="text"
                value={settings.model}
                onChange={(e) => updateSetting('model', e.target.value)}
                placeholder="gpt-4o-mini"
              />
            </div>
          </div>
        )}

        {activeTab === 'budget' && (
          <div className="settings-section">
            <h3>Token 预算控制</h3>
            <div className="form-group">
              <label>每日Token上限</label>
              <input
                type="number"
                value={settings.daily_token_limit}
                onChange={(e) => updateSetting('daily_token_limit', parseInt(e.target.value) || 0)}
              />
              <span className="hint">超限后自动降级到纯GBrain模式</span>
            </div>
            <div className="form-group">
              <label>每月Token上限</label>
              <input
                type="number"
                value={settings.monthly_token_limit}
                onChange={(e) => updateSetting('monthly_token_limit', parseInt(e.target.value) || 0)}
              />
            </div>
            <div className="form-group">
              <label>每月费用上限（USD）</label>
              <input
                type="number"
                value={settings.monthly_cost_limit}
                onChange={(e) => updateSetting('monthly_cost_limit', parseFloat(e.target.value) || 0)}
                step="0.5"
              />
              <span className="hint">重度用户预估：~$9/月</span>
            </div>
          </div>
        )}

        {activeTab === 'gate' && (
          <div className="settings-section">
            <h3>Gate 分流规则</h3>
            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={settings.custom_rules_enabled}
                  onChange={(e) => updateSetting('custom_rules_enabled', e.target.checked)}
                />
                启用自定义规则
              </label>
            </div>
            {settings.custom_rules_enabled && (
              <div className="form-group">
                <label>规则文件路径</label>
                <input
                  type="text"
                  value={settings.gate_rules_path}
                  onChange={(e) => updateSetting('gate_rules_path', e.target.value)}
                  placeholder="~/.mailknow/gate_rules.json"
                />
              </div>
            )}
            <p className="section-hint">
              Gate 5级分流规则：G0(垃圾) {'>'} G4(紧急) {'>'} G3(重要) {'>'} G2(通知) {'>'} G1(常规)
            </p>
          </div>
        )}

        {activeTab === 'scene' && (
          <div className="settings-section">
            <h3>场景推荐设置</h3>
            <div className="form-group">
              <label>每日推荐卡片上限</label>
              <input
                type="number"
                value={settings.max_daily_cards}
                onChange={(e) => updateSetting('max_daily_cards', parseInt(e.target.value) || 1)}
                min={1}
                max={20}
              />
            </div>
            <div className="form-group">
              <label>静默时段</label>
              <div className="time-range">
                <input
                  type="number"
                  value={settings.silent_hours_start}
                  onChange={(e) => updateSetting('silent_hours_start', parseInt(e.target.value) || 0)}
                  min={0}
                  max={23}
                />
                <span>时 至</span>
                <input
                  type="number"
                  value={settings.silent_hours_end}
                  onChange={(e) => updateSetting('silent_hours_end', parseInt(e.target.value) || 0)}
                  min={0}
                  max={23}
                />
                <span>时</span>
              </div>
              <span className="hint">静默期间不推送推荐卡片</span>
            </div>
          </div>
        )}

        {activeTab === 'sync' && (
          <div className="settings-section">
            <h3>邮件同步设置</h3>
            <div className="form-group">
              <label>同步间隔（分钟）</label>
              <input
                type="number"
                value={settings.sync_interval_minutes}
                onChange={(e) => updateSetting('sync_interval_minutes', parseInt(e.target.value) || 5)}
                min={1}
                max={60}
              />
            </div>
            <div className="form-group">
              <label>最大账号数</label>
              <input
                type="number"
                value={settings.max_accounts}
                onChange={(e) => updateSetting('max_accounts', parseInt(e.target.value) || 1)}
                min={1}
                max={10}
              />
            </div>
          </div>
        )}

        {activeTab === 'advanced' && (
          <div className="settings-section">
            <h3>高级设置</h3>
            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={settings.debug_mode}
                  onChange={(e) => updateSetting('debug_mode', e.target.checked)}
                />
                调试模式
              </label>
            </div>
            <div className="form-group">
              <label>数据存储路径</label>
              <input
                type="text"
                value={settings.data_path}
                onChange={(e) => updateSetting('data_path', e.target.value)}
                placeholder="~/.mailknow/data"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SettingsPage;

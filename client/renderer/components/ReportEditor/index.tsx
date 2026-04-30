import React, { useState, useCallback, useRef, useEffect } from 'react';
import './styles.css';

// ===== Types =====

export interface ReportSection {
  title: string;
  items: string[];
  source_count: number;
  source_ids: string[];
}

export interface WeeklyReportData {
  period_start: string;
  period_end: string;
  sections: ReportSection[];
  total_emails: number;
  generated_at: string;
  llm_used: boolean;
  deterministic_only: boolean;
  validation_passed: boolean;
  validation_warnings: string[];
}

export interface ReportEditorProps {
  report: WeeklyReportData;
  onSave: (report: WeeklyReportData) => Promise<void>;
  onExport: (format: 'markdown' | 'word') => Promise<void>;
  onShare: () => Promise<string | null>;
  onRegenerate: () => Promise<WeeklyReportData>;
  onSourceClick?: (sourceIds: string[]) => void;
}

// ===== Report Section Editor =====

const SectionEditor: React.FC<{
  section: ReportSection;
  index: number;
  onUpdate: (index: number, section: ReportSection) => void;
  onRemove: (index: number) => void;
  onSourceClick?: (sourceIds: string[]) => void;
}> = ({ section, index, onUpdate, onRemove, onSourceClick }) => {
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(section.title);
  const [editItems, setEditItems] = useState(section.items.join('\n'));

  const handleSave = () => {
    onUpdate(index, {
      ...section,
      title: editTitle,
      items: editItems.split('\n').filter((l) => l.trim()),
    });
    setEditing(false);
  };

  const handleCancel = () => {
    setEditTitle(section.title);
    setEditItems(section.items.join('\n'));
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="section-editor editing">
        <input
          className="section-title-input"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          placeholder="分类标题"
        />
        <textarea
          className="section-items-input"
          value={editItems}
          onChange={(e) => setEditItems(e.target.value)}
          placeholder="每行一条内容"
          rows={Math.max(3, editItems.split('\n').length)}
        />
        <div className="section-edit-actions">
          <button className="btn-save" onClick={handleSave}>保存</button>
          <button className="btn-cancel" onClick={handleCancel}>取消</button>
        </div>
      </div>
    );
  }

  return (
    <div className="section-editor">
      <div className="section-header">
        <h3 className="section-title">{section.title}</h3>
        <div className="section-actions">
          {section.source_ids.length > 0 && onSourceClick && (
            <button
              className="btn-source"
              onClick={() => onSourceClick(section.source_ids)}
              title="查看来源邮件"
            >
              📧 {section.source_count}封来源
            </button>
          )}
          <button className="btn-edit" onClick={() => setEditing(true)}>✏️ 编辑</button>
          <button className="btn-remove" onClick={() => onRemove(index)}>🗑️</button>
        </div>
      </div>
      <ul className="section-items">
        {section.items.map((item, i) => (
          <li key={i} className="section-item">{item}</li>
        ))}
      </ul>
    </div>
  );
};

// ===== Report Editor Component =====

export const ReportEditor: React.FC<ReportEditorProps> = ({
  report,
  onSave,
  onExport,
  onShare,
  onRegenerate,
  onSourceClick,
}) => {
  const [reportData, setReportData] = useState<WeeklyReportData>(report);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [modified, setModified] = useState(false);
  const [showValidation, setShowValidation] = useState(false);

  // Sync with prop changes
  useEffect(() => {
    setReportData(report);
    setModified(false);
  }, [report]);

  const handleSectionUpdate = useCallback((index: number, section: ReportSection) => {
    setReportData((prev) => {
      const sections = [...prev.sections];
      sections[index] = section;
      return { ...prev, sections };
    });
    setModified(true);
  }, []);

  const handleSectionRemove = useCallback((index: number) => {
    setReportData((prev) => ({
      ...prev,
      sections: prev.sections.filter((_, i) => i !== index),
    }));
    setModified(true);
  }, []);

  const handleAddSection = () => {
    setReportData((prev) => ({
      ...prev,
      sections: [
        ...prev.sections,
        { title: '新分类', items: [], source_count: 0, source_ids: [] },
      ],
    }));
    setModified(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(reportData);
      setModified(false);
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const newReport = await onRegenerate();
      setReportData(newReport);
      setModified(false);
    } finally {
      setRegenerating(false);
    }
  };

  const handleExport = async (format: 'markdown' | 'word') => {
    await onExport(format);
  };

  const handleShare = async () => {
    const url = await onShare();
    if (url) setShareUrl(url);
  };

  const toMarkdown = (): string => {
    const lines = [
      `# 周报 ${reportData.period_start} ~ ${reportData.period_end}`,
      '',
      `> 基于 ${reportData.total_emails} 封邮件自动生成 | ${
        reportData.llm_used ? 'GBrain + LLM' : 'GBrain 确定性推导'
      }`,
      '',
    ];

    if (reportData.validation_warnings.length > 0) {
      lines.push('> ⚠️ 以下内容可能包含非确定性推导，请人工审核：');
      reportData.validation_warnings.forEach((w) => lines.push(`> - ${w}`));
      lines.push('');
    }

    reportData.sections.forEach((s) => {
      lines.push(`## ${s.title}`);
      s.items.forEach((item) => lines.push(`- ${item}`));
      lines.push(`_（来源：${s.source_count}封邮件）_`);
      lines.push('');
    });

    lines.push('---');
    lines.push(`生成时间：${reportData.generated_at}`);

    return lines.join('\n');
  };

  return (
    <div className="report-editor">
      {/* Header */}
      <div className="report-header">
        <div className="report-title-area">
          <h2 className="report-title">
            周报 {reportData.period_start} ~ {reportData.period_end}
          </h2>
          <div className="report-meta">
            <span className="meta-item">📧 {reportData.total_emails}封邮件</span>
            <span className="meta-item">
              {reportData.llm_used ? '🤖 GBrain + LLM' : '📊 GBrain 确定性推导'}
            </span>
            {!reportData.validation_passed && (
              <button
                className="btn-validation-warn"
                onClick={() => setShowValidation(!showValidation)}
              >
                ⚠️ 含预测内容
              </button>
            )}
          </div>
        </div>

        <div className="report-toolbar">
          <button className="btn-regenerate" onClick={handleRegenerate} disabled={regenerating}>
            🔄 {regenerating ? '重新生成中...' : '重新生成'}
          </button>
          {modified && (
            <button className="btn-save" onClick={handleSave} disabled={saving}>
              💾 {saving ? '保存中...' : '保存修改'}
            </button>
          )}
          <div className="export-menu">
            <button className="btn-export" onClick={() => handleExport('markdown')}>
              📄 导出Markdown
            </button>
            <button className="btn-export" onClick={() => handleExport('word')}>
              📝 导出Word
            </button>
          </div>
          <button className="btn-share" onClick={handleShare}>
            🔗 分享
          </button>
        </div>
      </div>

      {/* Validation warnings */}
      {showValidation && reportData.validation_warnings.length > 0 && (
        <div className="validation-warnings">
          <h4>⚠️ 确定性验证警告</h4>
          <ul>
            {reportData.validation_warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
          <p className="validation-hint">以上内容可能包含预测性表述，建议人工审核后使用。</p>
        </div>
      )}

      {/* Share URL */}
      {shareUrl && (
        <div className="share-url">
          <span>分享链接：</span>
          <input type="text" readOnly value={shareUrl} className="share-url-input" />
          <button onClick={() => navigator.clipboard.writeText(shareUrl)}>复制</button>
        </div>
      )}

      {/* Sections */}
      <div className="report-sections">
        {reportData.sections.map((section, i) => (
          <SectionEditor
            key={i}
            section={section}
            index={i}
            onUpdate={handleSectionUpdate}
            onRemove={handleSectionRemove}
            onSourceClick={onSourceClick}
          />
        ))}

        <button className="btn-add-section" onClick={handleAddSection}>
          + 添加分类
        </button>
      </div>

      {/* Footer */}
      <div className="report-footer">
        <span className="generated-at">生成时间：{reportData.generated_at}</span>
      </div>
    </div>
  );
};

export default ReportEditor;

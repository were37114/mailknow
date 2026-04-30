import React from 'react';
import './styles.css';

// ===== Types =====

export type AttachmentType = 'pdf' | 'excel' | 'word' | 'image' | 'zip' | 'other';

export interface AttachmentData {
  attachment_id: string;
  filename: string;
  file_type: AttachmentType;
  file_size: number;
  text_content?: string;
  page_count?: number;
  llm_summary?: string;
  preview_available?: boolean;
  email_id: string;
}

export interface AttachmentPreviewProps {
  attachment: AttachmentData;
  onPreview?: (attachment: AttachmentData) => void;
  onDownload?: (attachment: AttachmentData) => void;
}

// ===== Helper functions =====

const TYPE_ICONS: Record<AttachmentType, string> = {
  pdf: '📄',
  excel: '📊',
  word: '📝',
  image: '🖼️',
  zip: '📦',
  other: '📎',
};

const TYPE_LABELS: Record<AttachmentType, string> = {
  pdf: 'PDF',
  excel: 'Excel',
  word: 'Word',
  image: '图片',
  zip: '压缩包',
  other: '附件',
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ===== Attachment Preview Component =====

export const AttachmentPreview: React.FC<AttachmentPreviewProps> = ({
  attachment,
  onPreview,
  onDownload,
}) => {
  const icon = TYPE_ICONS[attachment.file_type] || '📎';
  const label = TYPE_LABELS[attachment.file_type] || '附件';

  return (
    <div className="attachment-preview">
      {/* Icon & filename */}
      <div className="attachment-header">
        <span className="attachment-icon">{icon}</span>
        <div className="attachment-info">
          <span className="attachment-filename" title={attachment.filename}>
            {attachment.filename}
          </span>
          <span className="attachment-meta">
            {label} · {formatFileSize(attachment.file_size)}
            {attachment.page_count ? ` · ${attachment.page_count}页` : ''}
          </span>
        </div>
      </div>

      {/* LLM summary */}
      {attachment.llm_summary && (
        <div className="attachment-summary">
          <span className="summary-label">🤖 AI摘要</span>
          <p className="summary-text">{attachment.llm_summary}</p>
        </div>
      )}

      {/* Text content preview */}
      {attachment.text_content && (
        <details className="attachment-content">
          <summary>提取内容</summary>
          <pre className="content-text">{attachment.text_content.slice(0, 2000)}</pre>
          {attachment.text_content.length > 2000 && (
            <span className="content-truncated">...（内容过长已截断）</span>
          )}
        </details>
      )}

      {/* Actions */}
      <div className="attachment-actions">
        {onPreview && (
          <button className="btn-preview" onClick={() => onPreview(attachment)}>
            预览
          </button>
        )}
        {onDownload && (
          <button className="btn-download" onClick={() => onDownload(attachment)}>
            下载
          </button>
        )}
      </div>
    </div>
  );
};

// ===== Attachment List =====

export interface AttachmentListProps {
  attachments: AttachmentData[];
  onPreview?: (attachment: AttachmentData) => void;
  onDownload?: (attachment: AttachmentData) => void;
}

export const AttachmentList: React.FC<AttachmentListProps> = ({
  attachments,
  onPreview,
  onDownload,
}) => {
  if (attachments.length === 0) {
    return <div className="attachments-empty">无附件</div>;
  }

  return (
    <div className="attachment-list">
      {attachments.map((att) => (
        <AttachmentPreview
          key={att.attachment_id}
          attachment={att}
          onPreview={onPreview}
          onDownload={onDownload}
        />
      ))}
    </div>
  );
};

export default AttachmentPreview;
